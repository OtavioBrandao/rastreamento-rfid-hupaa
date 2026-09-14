from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from rfid_ingestion.parsing import build_event

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "identix" / "tag-read.json"
)


class ParsingTests(unittest.TestCase):
    def test_identix_fixture_preserves_current_canonical_contract(self) -> None:
        raw_payload = FIXTURE_PATH.read_bytes()

        event = build_event(
            topic="easy/dev/hupaa/portal-01/reader-01/readings",
            qos=1,
            retain=False,
            payload=raw_payload,
        )

        self.assertIsNone(event["parse_error"])
        self.assertEqual(event["validation_errors"], [])
        self.assertEqual(event["topic"], "easy/dev/hupaa/portal-01/reader-01/readings")
        self.assertEqual(event["qos"], 1)
        self.assertIs(event["retain"], False)
        self.assertEqual(
            {
                field: event["payload_json"][field]
                for field in ("epc", "readerid", "antenna", "rssi", "timestamp")
            },
            {
                "epc": "E2801190A502006016C32F62",
                "readerid": "EZ700-PORTAL-01",
                "antenna": 1,
                "rssi": -3880,
                "timestamp": "1632759395291",
            },
        )
        self.assertEqual(event["payload_json"]["tid"], "E280119020004F62B6190300")

    def test_valid_json_and_metadata_are_preserved(self) -> None:
        payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        payload["firmware_extra_field"] = {"enabled": True}
        encoded = json.dumps(payload).encode("utf-8")
        received_at = datetime(2026, 8, 17, 18, 30, tzinfo=timezone.utc)

        event = build_event(
            topic="rfid/portal-01/tags",
            qos=1,
            retain=True,
            payload=encoded,
            received_at=received_at,
        )

        self.assertEqual(event["received_at_utc"], "2026-08-17T18:30:00.000Z")
        self.assertEqual(event["topic"], "rfid/portal-01/tags")
        self.assertEqual(event["qos"], 1)
        self.assertIs(event["retain"], True)
        self.assertEqual(event["payload_original"], encoded.decode("utf-8"))
        self.assertEqual(event["payload_encoding"], "utf-8")
        self.assertEqual(event["payload_json"], payload)
        self.assertEqual(
            event["payload_json"]["firmware_extra_field"], {"enabled": True}
        )
        self.assertIsNone(event["parse_error"])

    def test_invalid_json_is_recorded_without_exception(self) -> None:
        event = build_event(
            topic="rfid/portal-02/tags",
            qos=0,
            retain=False,
            payload=b'{"epc":',
        )

        self.assertEqual(event["payload_original"], '{"epc":')
        self.assertIsNone(event["payload_json"])
        self.assertIn("JSON inválido", event["parse_error"])

    def test_non_utf8_payload_is_preserved_as_base64(self) -> None:
        event = build_event(
            topic="rfid/portal-03/tags",
            qos=0,
            retain=False,
            payload=b"\xff\xfe",
        )

        self.assertEqual(event["payload_original"], "//4=")
        self.assertEqual(event["payload_encoding"], "base64")
        self.assertIsNone(event["payload_json"])
        self.assertIn("UTF-8", event["parse_error"])


if __name__ == "__main__":
    unittest.main()
