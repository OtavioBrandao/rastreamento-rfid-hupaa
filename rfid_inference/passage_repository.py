"""Consultas de topologia histórica e persistência idempotente de passagens."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from db.models import LeituraBruta, MapeamentoAntenaPortal, Passagem
from rfid_inference.debounce import ConsolidatedObservation

from .passage import DetectedPassage, PortalObservation


class PassageRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def resolve(self, observation: ConsolidatedObservation) -> PortalObservation | None:
        """Exige exatamente um mapeamento cobrindo a observação completa."""
        mapping = MapeamentoAntenaPortal
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(mapping.id, mapping.portal_id, mapping.lado, mapping.zona_id,
                       mapping.inicio, mapping.fim).where(
                    mapping.antena_id == observation.antenna_id,
                    mapping.inicio <= observation.last_seen_at,
                    or_(mapping.fim.is_(None), mapping.fim > observation.first_seen_at),
                )
            ).all()
        if len(rows) != 1:
            return None
        row = rows[0]
        if row.inicio > observation.first_seen_at or (
            row.fim is not None and row.fim <= observation.last_seen_at
        ):
            return None
        return PortalObservation(
            epc=observation.epc,
            portal_id=row.portal_id,
            antenna_id=observation.antenna_id,
            side=row.lado,
            zone_id=row.zona_id,
            mapping_id=row.id,
            first_seen_at=observation.first_seen_at,
            last_seen_at=observation.last_seen_at,
            first_reading_id=observation.first_reading_id,
            last_reading_id=observation.last_reading_id,
            first_event_id=observation.first_event_id,
            last_event_id=observation.last_event_id,
        )

    def origin_active(self, origin: PortalObservation, destination: PortalObservation, *,
                      grace: timedelta, hold: timedelta) -> bool:
        """A antena de origem leu a tag durante o destino (após a sobreposição)?

        A janela termina ``hold`` depois da última leitura do destino; essas
        leituras já foram persistidas quando o debounce finaliza a observação.
        """
        with self.engine.connect() as connection:
            return bool(connection.scalar(select(exists().where(
                LeituraBruta.epc == origin.epc,
                LeituraBruta.antena_id == origin.antenna_id,
                LeituraBruta.lido_em > destination.first_seen_at + grace,
                LeituraBruta.lido_em <= destination.last_seen_at + hold,
            ))))

    def persist(self, passage: DetectedPassage) -> bool:
        """Retorna True se inserida, False se as evidências já existiam."""
        statement = insert(Passagem).values(
            epc=passage.epc,
            portal_id=passage.portal_id,
            antena_origem_id=passage.first_antenna_id,
            antena_destino_id=passage.second_antenna_id,
            leitura_origem_id=passage.first_reading_id,
            leitura_destino_id=passage.second_reading_id,
            detectada_em=passage.detected_at,
            direcao=None,
        ).on_conflict_do_nothing(
            index_elements=[Passagem.leitura_origem_id, Passagem.leitura_destino_id]
        ).returning(Passagem.id)
        with self.engine.begin() as connection:
            return connection.execute(statement).scalar_one_or_none() is not None
