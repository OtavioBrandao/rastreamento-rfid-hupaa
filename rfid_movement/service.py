"""Regras do ledger; chamador controla BEGIN/COMMIT/ROLLBACK."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.engine import Connection

from . import repository
from .types import MovementEvent, MovementWriteResult

logger = logging.getLogger(__name__)


def append_automatic_movement(connection: Connection, passage_id: int) -> MovementWriteResult:
    passage = repository.load_passage(connection, passage_id)
    if passage is None:
        return MovementWriteResult("passage_missing", passagem_id=passage_id)
    valid = (
        passage["direcao_status"] == "confirmed"
        and passage["direcao"] in ("a_para_b", "b_para_a")
        and passage["zona_origem_id"] is not None
        and passage["zona_destino_id"] is not None
        and passage["zona_origem_id"] != passage["zona_destino_id"]
        and passage["leitura_origem_id"] is not None
        and passage["leitura_destino_id"] is not None
        and passage["epc"]
        and passage["portal_id"] is not None
        and passage["detectada_em"] is not None
    )
    if not valid:
        logger.info("rfid_movement_invalid_passage", extra={"passage_id": passage_id})
        return MovementWriteResult("invalid_passage", passagem_id=passage_id)
    equipment_ids = repository.resolve_equipment(
        connection, passage["epc"], passage["detectada_em"]
    )
    if not equipment_ids:
        logger.info("rfid_movement_unresolved_epc", extra={
            "passage_id": passage_id, "epc": passage["epc"],
        })
        return MovementWriteResult("unresolved_epc", passagem_id=passage_id)
    if len(equipment_ids) != 1:
        logger.info("rfid_movement_ambiguous_association", extra={
            "passage_id": passage_id, "epc": passage["epc"],
        })
        return MovementWriteResult("ambiguous_association", passagem_id=passage_id)
    event = MovementEvent(
        equipamento_id=equipment_ids[0],
        epc=passage["epc"],
        portal_id=passage["portal_id"],
        zona_origem_id=passage["zona_origem_id"],
        zona_destino_id=passage["zona_destino_id"],
        passagem_id=passage_id,
        leitura_origem_id=passage["leitura_origem_id"],
        leitura_destino_id=passage["leitura_destino_id"],
        movimentada_em=passage["detectada_em"],
        origem_registro="passagem_automatica",
    )
    movement_id, inserted = repository.append(connection, event)
    status = "recorded" if inserted else "duplicate"
    logger.info(f"rfid_movement_{status}", extra={
        "movement_id": movement_id, "equipment_id": event.equipamento_id,
        "passage_id": passage_id, "epc": event.epc, "portal_id": event.portal_id,
        "origin_zone_id": event.zona_origem_id,
        "destination_zone_id": event.zona_destino_id,
    })
    return MovementWriteResult(status, movement_id, event.equipamento_id, passage_id)


def append_manual_correction(
    connection: Connection, *, equipamento_id: int, zona_destino_id: int,
    movimentada_em: datetime, justificativa: str,
    registro_anterior_id: int | None = None, zona_origem_id: int | None = None,
) -> MovementWriteResult:
    if movimentada_em.tzinfo is None or movimentada_em.utcoffset() is None:
        raise ValueError("movimentada_em exige fuso horário")
    if not justificativa or not justificativa.strip():
        raise ValueError("justificativa é obrigatória")
    if zona_origem_id == zona_destino_id:
        raise ValueError("origem e destino devem ser distintos")
    if not repository.equipment_exists(connection, equipamento_id):
        raise ValueError("equipamento inexistente")
    if registro_anterior_id is not None:
        previous = repository.get_movement(connection, registro_anterior_id)
        if previous is None or previous["equipamento_id"] != equipamento_id:
            raise ValueError("registro anterior inexistente ou de outro equipamento")
        if zona_origem_id is None:
            zona_origem_id = previous["zona_destino_id"]
        elif zona_origem_id != previous["zona_destino_id"]:
            raise ValueError("origem deve corresponder ao destino do registro anterior")
        if zona_origem_id == zona_destino_id:
            raise ValueError("correção sem mudança de zona")
    event = MovementEvent(
        equipamento_id=equipamento_id,
        zona_origem_id=zona_origem_id,
        zona_destino_id=zona_destino_id,
        movimentada_em=movimentada_em,
        origem_registro="correcao_manual",
        justificativa=justificativa.strip(),
        registro_anterior_id=registro_anterior_id,
    )
    movement_id, _ = repository.append(connection, event)
    logger.info("rfid_movement_manual_correction", extra={
        "movement_id": movement_id, "equipment_id": equipamento_id,
        "origin_zone_id": zona_origem_id, "destination_zone_id": zona_destino_id,
    })
    return MovementWriteResult("recorded", movement_id, equipamento_id)
