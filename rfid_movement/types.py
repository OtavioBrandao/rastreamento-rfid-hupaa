"""Contratos imutáveis do histórico, independentes do ORM."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class MovementEvent:
    """Estrutura Movement Event usada por rfid_movement.types.

    Campos: equipamento_id, zona_origem_id, zona_destino_id, movimentada_em, origem_registro, epc, portal_id, passagem_id, leitura_origem_id, leitura_destino_id, justificativa, registro_anterior_id, referencia."""
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
    referencia: str | None = None  # ISS-025: só em correcao_manual


@dataclass(frozen=True)
class MovementWriteResult:
    """Estrutura Movement Write Result usada por rfid_movement.types.

    Campos: status, movement_id, equipamento_id, passagem_id."""
    status: Literal[
        "recorded", "duplicate", "invalid_passage", "unresolved_epc",
        "ambiguous_association", "passage_missing",
    ]
    movement_id: int | None = None
    equipamento_id: int | None = None
    passagem_id: int | None = None


@dataclass(frozen=True)
class MovementRecord:
    """Estrutura Movement Record usada por rfid_movement.types.

    Campos: id, equipamento_id, epc, origem_registro, zona_origem_id, zona_origem, zona_destino_id, zona_destino, portal_id, portal, passagem_id, leitura_origem_id, leitura_destino_id, movimentada_em, registrado_em, justificativa, registro_anterior_id, referencia."""
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
    referencia: str | None = None


@dataclass(frozen=True)
class MovementPage:
    """Estrutura Movement Page usada por rfid_movement.types.

    Campos: items, page, size, total, pages."""
    items: tuple[MovementRecord, ...]
    page: int
    size: int
    total: int
    pages: int
