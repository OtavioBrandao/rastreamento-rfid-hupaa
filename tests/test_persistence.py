from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rfid_ingestion.persistence import JsonlEventStore


class JsonlEventStoreTests(unittest.TestCase):
    def test_creates_parent_directory_and_file(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "nested" / "events.jsonl"
            store = JsonlEventStore(output)

            self.assertTrue(output.parent.is_dir())
            store.append({"sequence": 1})
            self.assertTrue(output.is_file())
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                {"sequence": 1},
            )

    def test_appends_multiple_events_without_overwriting(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "events.jsonl"
            store = JsonlEventStore(output)

            store.append({"sequence": 1})
            store.append({"sequence": 2})

            lines = output.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual([json.loads(line) for line in lines], [
                {"sequence": 1},
                {"sequence": 2},
            ])


if __name__ == "__main__":
    unittest.main()
