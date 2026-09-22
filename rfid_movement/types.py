"""Contratos imutáveis do histórico, independentes do ORM."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class MovementEvent:
    equipamento_id: int
    zona_origem_id: int | None
    zona_destino_id: int
    movimentada_em: datetime
    origem_registro: Literal["passagem_automatica", "correcao_manual"]
    epc: str | None = None
    portal_id: int | None = None
    passagem_id: int | None = None
    leitura_origem_id: int | None = None
    leitura_destino_id: int | None = None
    justificativa: str | None = None
    registro_anterior_id: int | None = None


@dataclass(frozen=True)
class MovementWriteResult:
    status: Literal[
        "recorded", "duplicate", "invalid_passage", "unresolved_epc",
        "ambiguous_association", "passage_missing",
    ]
    movement_id: int | None = None
    equipamento_id: int | None = None
    passagem_id: int | None = None


@dataclass(frozen=True)
class MovementRecord:
    id: int
    equipamento_id: int
    epc: str | None
    origem_registro: str
    zona_origem_id: int | None
    zona_origem: str | None
    zona_destino_id: int
    zona_destino: str
    portal_id: int | None
    portal: str | None
    passagem_id: int | None
    leitura_origem_id: int | None
    leitura_destino_id: int | None
    movimentada_em: datetime | None
    registrado_em: datetime
    justificativa: str | None
    registro_anterior_id: int | None


@dataclass(frozen=True)
class MovementPage:
    items: tuple[MovementRecord, ...]
    page: int
    size: int
    total: int
    pages: int
