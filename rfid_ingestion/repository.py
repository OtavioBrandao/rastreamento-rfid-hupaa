"""Persistência transacional de eventos canônicos, independente de MQTT."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from db.models import Antena, Leitor, LeituraBruta


@dataclass(frozen=True, slots=True)
class PersistenceResult:
    status: Literal["inserted", "duplicate", "rejected"]
    reading_id: int | None = None
    reason: str | None = None


class PersistenceError(RuntimeError):
    """Falha de banco: não confirmar processamento nem divulgar parâmetros."""


def _utc(value: str) -> datetime:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("timestamp de persistência exige fuso horário")
    return instant.astimezone(timezone.utc)


class RawReadingRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def persist(self, envelope: dict) -> PersistenceResult:
        canonical = envelope["canonical_event"]
        if canonical is None:
            return PersistenceResult("rejected", reason="invalid_input")
        try:
            with self.engine.begin() as connection:
                topology = connection.execute(
                    select(Leitor.id, Antena.id).outerjoin(
                        Antena, and_(Antena.leitor_id == Leitor.id,
                                     Antena.porta_numero == canonical["antenna"],
                                     Antena.ativo.is_(True))
                    ).where(Leitor.reader_id == canonical["reader_id"])
                ).one_or_none()
                if topology is None:
                    return PersistenceResult("rejected", reason="unknown_reader")
                if topology[1] is None:
                    return PersistenceResult("rejected", reason="unknown_antenna")
                statement = insert(LeituraBruta).values(
                    event_id=canonical["event_id"], antena_id=topology[1],
                    epc=canonical["epc"], rssi=canonical["rssi"],
                    lido_em=_utc(canonical["timestamp"]),
                    recebido_em=_utc(envelope["received_at_utc"]),
                    dados_origem={"metadata": canonical.get("metadata", {}),
                                  **{key: envelope[key] for key in
                                     ("topic", "adapter", "qos", "retain")}},
                ).on_conflict_do_nothing(
                    index_elements=[LeituraBruta.event_id]
                ).returning(LeituraBruta.id)
                reading_id = connection.execute(statement).scalar_one_or_none()
            # Só devolver sucesso após a confirmação da transação.
            return PersistenceResult("inserted", reading_id) if reading_id is not None else PersistenceResult("duplicate")
        except SQLAlchemyError:
            raise PersistenceError("falha PostgreSQL") from None
