"""Persistência append-only em JSON Lines."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any, Mapping


class JsonlEventStore:
    """Grava um evento JSON por linha e faz flush após cada append."""

    def __init__(self, path: Path) -> None:
        """Inicializa JsonlEventStore com as dependências e valores recebidos."""
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def append(self, event: Mapping[str, Any]) -> None:
        """Acrescenta um envelope JSONL sob lock e faz flush do buffer Python.

        Não executa fsync; a garantia de persistência de leituras aceitas depende
        do commit PostgreSQL e da política de durabilidade do banco/broker.
        """
        serialized = json.dumps(
            event,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        with self._lock, self.path.open(
            "a", encoding="utf-8", newline="\n"
        ) as output:
            output.write(serialized)
            output.write("\n")
            output.flush()
