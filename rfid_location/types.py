"""Resultados e regra temporal da projeção, sem dependência do banco."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ProjectionStatus = Literal[
    "updated", "duplicate", "stale", "same_timestamp_conflict",
    "invalid_passage", "unresolved_epc", "ambiguous_association",
    "passage_missing", "equipment_missing",
]


@dataclass(frozen=True)
class LocationProjectionResult:
    """Estrutura Location Projection Result usada por rfid_location.types.

    Campos: status, equipment_id, movement_id, passage_id, previous_zone_id, destination_zone_id, previous_detected_at, movement_at, versao."""
    status: ProjectionStatus
    equipment_id: int | None = None
    movement_id: int | None = None
    passage_id: int | None = None
    previous_zone_id: int | None = None
    destination_zone_id: int | None = None
    previous_detected_at: datetime | None = None
    movement_at: datetime | None = None
    versao: int | None = None  # ISS-025: versão do equipamento após o movimento


def decide_projection(
    movement_at: datetime, previous_at: datetime | None,
    movement_id: int, previous_movement_id: int | None,
) -> Literal["updated", "duplicate", "stale", "same_timestamp_conflict"]:
    """Compara tempo e identidade do movimento: updated, stale, duplicate ou same_timestamp_conflict."""
    if previous_at is None or movement_at > previous_at:
        return "updated"
    if movement_at < previous_at:
        return "stale"
    if movement_id == previous_movement_id:
        return "duplicate"
    return "same_timestamp_conflict"
