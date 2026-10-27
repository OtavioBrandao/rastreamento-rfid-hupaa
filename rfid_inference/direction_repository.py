"""Carrega evidências e topologia histórica; atualiza somente passagens pendentes."""

from __future__ import annotations

from sqlalchemy import or_, select, update
from sqlalchemy.engine import Engine

from db.models import Antena, LeituraBruta, MapeamentoAntenaPortal, Passagem, Portal

from .direction import (
    DirectionContext,
    DirectionEvidence,
    DirectionInferenceResult,
    DirectionMapping,
)


class DirectionRepository:
    """Consulta evidências/topologia histórica e persiste a direção de forma idempotente."""
    def __init__(self, engine: Engine):
        """Inicializa DirectionRepository com as dependências e valores recebidos."""
        self.engine = engine

    def pending_ids(self, limit: int = 100) -> tuple[int, ...]:
        """Lista IDs de passagens ainda sem direção em ordem crescente e com limite."""
        if limit < 1:
            raise ValueError("limit deve ser positivo")
        with self.engine.connect() as connection:
            return tuple(connection.scalars(
                select(Passagem.id).where(Passagem.direcao_status.is_(None))
                .order_by(Passagem.id).limit(limit)
            ))

    def load(self, passage_id: int) -> DirectionContext | None:
        """Carrega contexto, leituras e topologia histórica de uma passagem ainda sem direção."""
        with self.engine.connect() as connection:
            row = connection.execute(
                select(
                    Passagem.id, Passagem.epc, Passagem.portal_id,
                    Passagem.antena_origem_id, Passagem.antena_destino_id,
                    Passagem.leitura_origem_id, Passagem.leitura_destino_id,
                    Portal.id.label("existing_portal_id"),
                )
                .outerjoin(Portal, Portal.id == Passagem.portal_id)
                .where(Passagem.id == passage_id, Passagem.direcao_status.is_(None))
            ).one_or_none()
            if row is None:
                return None

            def historical_zones(at) -> tuple[int, int] | None:
                """Resolve uma única zona por lado na topologia vigente no instante; ambiguidades devolvem None."""
                if at is None or row.existing_portal_id is None:
                    return None
                mappings = connection.execute(
                    select(MapeamentoAntenaPortal.lado, MapeamentoAntenaPortal.zona_id)
                    .where(
                        MapeamentoAntenaPortal.portal_id == row.portal_id,
                        MapeamentoAntenaPortal.inicio <= at,
                        or_(MapeamentoAntenaPortal.fim.is_(None),
                            MapeamentoAntenaPortal.fim > at),
                    )
                ).all()
                sides: dict[str, set[int]] = {"a": set(), "b": set()}
                for side, zone_id in mappings:
                    if side not in sides:
                        return None
                    sides[side].add(zone_id)
                if len(sides["a"]) != 1 or len(sides["b"]) != 1:
                    return None
                zone_a, zone_b = next(iter(sides["a"])), next(iter(sides["b"]))
                if zone_a == zone_b:
                    return None
                return zone_a, zone_b

            def evidence(antenna_id: int | None, reading_id: int | None) -> DirectionEvidence:
                """Carrega a leitura e seus mapeamentos temporais para compor a evidência de direção."""
                reading = connection.execute(
                    select(LeituraBruta.antena_id, LeituraBruta.epc, LeituraBruta.lido_em,
                           Antena.leitor_id)
                    .join(Antena, Antena.id == LeituraBruta.antena_id)
                    .where(LeituraBruta.id == reading_id)
                ).one_or_none() if reading_id is not None else None
                mappings: tuple[DirectionMapping, ...] = ()
                if reading is not None:
                    mappings = tuple(
                        DirectionMapping(portal_id=item.portal_id, side=item.lado,
                                         zone_id=item.zona_id)
                        for item in connection.execute(
                            select(
                                MapeamentoAntenaPortal.portal_id,
                                MapeamentoAntenaPortal.lado,
                                MapeamentoAntenaPortal.zona_id,
                            ).where(
                                MapeamentoAntenaPortal.antena_id == antenna_id,
                                MapeamentoAntenaPortal.inicio <= reading.lido_em,
                                or_(MapeamentoAntenaPortal.fim.is_(None),
                                    MapeamentoAntenaPortal.fim > reading.lido_em),
                            )
                        ).all()
                    )
                return DirectionEvidence(
                    antenna_id=antenna_id, reading_id=reading_id,
                    observed_at=reading.lido_em if reading else None,
                    epc=reading.epc if reading else None,
                    reading_antenna_id=reading.antena_id if reading else None,
                    mappings=mappings,
                    reader_id=reading.leitor_id if reading else None,
                )

            first = evidence(row.antena_origem_id, row.leitura_origem_id)
            second = evidence(row.antena_destino_id, row.leitura_destino_id)
            zones_first = historical_zones(first.observed_at)
            zones_second = historical_zones(second.observed_at)
            zones = zones_first if zones_first == zones_second else None
            modo = connection.scalar(select(Portal.modo).where(Portal.id == row.portal_id))
            return DirectionContext(
                passage_id=row.id, epc=row.epc, portal_id=row.portal_id,
                zone_a_id=zones[0] if zones else None,
                zone_b_id=zones[1] if zones else None,
                first=first, second=second, entry_portal=modo == "entrada",
            )

    def persist(self, result: DirectionInferenceResult) -> bool:
        """Compare-and-set: nenhuma decisão existente é rebaixada por retry."""
        statement = (
            update(Passagem)
            .where(Passagem.id == result.passage_id, Passagem.direcao_status.is_(None))
            .values(
                direcao=result.direction,
                direcao_status=result.status,
                direcao_regra=result.rule,
                zona_origem_id=result.origin_zone_id,
                zona_destino_id=result.destination_zone_id,
            )
        )
        with self.engine.begin() as connection:
            return connection.execute(statement).rowcount == 1
