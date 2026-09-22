"""Componentes de domínio para inferência RFID, sem dependência de transporte."""

from .debounce import (
    ConsolidatedObservation,
    DebounceCounters,
    DebounceProcessor,
    DebounceReading,
    DebounceResult,
)

__all__ = [
    "ConsolidatedObservation",
    "DebounceCounters",
    "DebounceProcessor",
    "DebounceReading",
    "DebounceResult",
]
