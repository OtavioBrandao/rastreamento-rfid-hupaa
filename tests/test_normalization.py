"""Validação sintética da ISS-005; nenhuma evidência física é inferida."""

import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from rfid_ingestion.config import Settings
from rfid_ingestion.mqtt_client import MqttReceiver
from rfid_ingestion.normalization import ADAPTERS
from rfid_ingestion.parsing import build_event
from rfid_ingestion.persistence import JsonlEventStore
from rfid_ingestion.repository import PersistenceResult
from rfid_ingestion.simulator import _parser, _payload
from rfid_ingestion.topics import reading_topic

FIXTURE = Path("tests/fixtures/identix/tag-read.json")


class NormalizationTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(FIXTURE.read_bytes())
        self.reader = self.payload["readerid"]
        self.settings = Settings(ez700_timestamp_format="epoch_ms")

    def build(self, payload=None, settings=None, **kwargs):
        raw = payload if isinstance(payload, bytes) else json.dumps(self.payload if payload is None else payload).encode()
        return build_event(topic=kwargs.pop("topic", reading_topic(self.reader)), qos=1,
                           retain=False, payload=raw, settings=settings or self.settings, **kwargs)

    def test_fixture_and_unknown_rssi(self):
        event = self.build()
        self.assertEqual(event["validation_errors"], [])
        canonical = event["canonical_event"]
        self.assertEqual(canonical["timestamp"], "2021-09-27T16:16:35.291000Z")
        self.assertIsNone(canonical["rssi"])
        self.assertEqual(canonical["metadata"]["rssi_original"], -3880)
        self.assertEqual(canonical["metadata"]["source_fields"]["tid"], self.payload["tid"])

    def test_numeric_timestamp_requires_explicit_profile(self):
        self.assertIsNone(self.build(settings=Settings())["canonical_event"])

    def test_ez700_simulator_clock_requires_explicit_epoch_ms(self):
        with patch.dict("os.environ", {}, clear=True):
            parser = _parser()
        for options in ([], ["--format", "ez700"]):
            args = parser.parse_args(options + ["--reader-id", self.reader])
            with patch("rfid_ingestion.simulator.time.time_ns", return_value=1632759395291999999):
                payload = _payload(args)
            self.assertEqual(payload["timestamp"], "1632759395291")
            self.assertIsNone(self.build(payload, Settings())["canonical_event"])
            self.assertEqual(self.build(payload)["canonical_event"]["timestamp"],
                             "2021-09-27T16:16:35.291000Z")

    def test_simulator_timestamps_and_explicit_override(self):
        with patch.dict("os.environ", {}, clear=True):
            parser = _parser()
        args = parser.parse_args(["--format", "simulator", "--reader-id", self.reader])
        payload = _payload(args)
        self.assertIsNotNone(self.build(payload, Settings(normalization_adapter="simulator"))["canonical_event"])
        self.assertTrue(payload["observed_at"].endswith("+00:00"))
        for source_format, key in (("ez700", "timestamp"), ("simulator", "observed_at")):
            args = parser.parse_args(["--format", source_format, "--timestamp", "explicit-replay"])
            self.assertEqual(_payload(args)[key], "explicit-replay")

    def test_simulator_and_equivalence(self):
        equivalent = {"tag": self.payload["epc"], "port": 1,
                      "signal": {"value": -3880, "unit": "unknown"},
                      "observed_at": "2021-09-27T13:16:35.291-03:00"}
        ez = self.build()["canonical_event"]
        sim = self.build(equivalent, replace(self.settings, reader_adapters={self.reader: "simulator"}))["canonical_event"]
        for field in ("epc", "antenna", "rssi", "timestamp", "reader_id"):
            self.assertEqual(ez[field], sim[field], field)
        with patch.dict("os.environ", {}, clear=True):
            args = _parser().parse_args(["--format", "simulator", "--reader-id", self.reader])
        native = self.build(_payload(args), replace(self.settings, normalization_adapter="simulator"))["canonical_event"]
        self.assertEqual(native["rssi"], -38.8)

    def test_optional_identity_and_extras(self):
        del self.payload["readerid"]
        self.payload["extra"] = {"future": [1, "olá"]}
        result = self.build()["canonical_event"]
        self.assertEqual(result["reader_id"], self.reader)
        self.assertEqual(result["metadata"]["source_fields"]["extra"], self.payload["extra"])

    def test_reader_conflicts_and_two_readers(self):
        for key in ("readerid", "reader_id"):
            event = self.build(self.payload | {key: "different"})
            self.assertIn("diverge", event["validation_errors"][0])
        second = self.build(self.payload | {"readerid": "second"}, topic=reading_topic("second"))["canonical_event"]
        first = self.build()["canonical_event"]
        self.assertNotEqual(first["reader_id"], second["reader_id"])
        self.assertNotEqual(first["event_id"], second["event_id"])

    def test_invalid_fields(self):
        for key, values in {"epc": [None, "", " ", 3], "antenna": [None, 0, -1, True, 1.5, "1"],
                            "rssi": [None, "-38", True], "timestamp": [None, "", "yesterday", "2026-01-01T00:00:00", "123"]}.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    event = self.build(self.payload | {key: value})
                    self.assertIsNone(event["canonical_event"])
                    self.assertTrue(event["validation_errors"])
            missing = self.payload.copy()
            del missing[key]
            self.assertIsNone(self.build(missing)["canonical_event"])

    def test_json_utf8_objects_and_limits(self):
        for raw in (b'{', b'\xff', b'[]', b'null', b'1', b'{"rssi":NaN}', b'{"extra":1e9999}', b'[' * 2000):
            with self.subTest(raw=raw[:20]):
                event = self.build(raw)
                self.assertIsNone(event["canonical_event"])
                self.assertTrue(event["parse_error"] or event["validation_errors"])
        raw = FIXTURE.read_bytes()
        self.assertIsNotNone(self.build(raw, replace(self.settings, max_payload_bytes=len(raw)))["canonical_event"])
        event = self.build(raw, replace(self.settings, max_payload_bytes=len(raw)-1))
        self.assertIsNone(event["payload_json"])
        self.assertEqual(event["payload_original"], raw.decode())
        self.assertIn("MQTT_MAX_PAYLOAD_BYTES", event["validation_errors"][0])

    def test_timestamp_precision_and_calendar(self):
        settings = Settings()
        event = self.build(self.payload | {"timestamp": "2026-09-07T10:00:00.123456-03:00"}, settings)
        self.assertEqual(event["canonical_event"]["timestamp"], "2026-09-07T13:00:00.123456Z")
        for timestamp in ("2026-02-30T10:00:00Z", "2026-09-07T10:00:00+25:00", "2026-09-07T10:00:00.1234567Z"):
            self.assertIsNone(self.build(self.payload | {"timestamp": timestamp}, settings)["canonical_event"])

    def test_stable_redelivery_identity_and_scope(self):
        first = self.build()["canonical_event"]["event_id"]
        self.assertEqual(first, self.build(received_at=datetime(2000, 1, 1, tzinfo=timezone.utc))["canonical_event"]["event_id"])
        self.assertNotEqual(first, self.build(self.payload | {"antenna": 2})["canonical_event"]["event_id"])
        self.assertNotEqual(first, self.build(topic=reading_topic(self.reader, portal="other"))["canonical_event"]["event_id"])

    def test_unknown_adapter_and_extension(self):
        settings = replace(self.settings, normalization_adapter="new")
        self.assertIn("adapter desconhecido", self.build(settings=settings)["validation_errors"])
        with patch.dict(ADAPTERS, {"new": ADAPTERS["ez700"]}):
            self.assertIsNotNone(self.build(settings=settings)["canonical_event"])
        with patch.dict(ADAPTERS, {"new": Mock(side_effect=RuntimeError("private payload"))}):
            self.assertEqual(self.build(settings=settings)["validation_errors"], ["falha interna do adapter"])

    def test_configuration(self):
        settings = Settings.from_env({"RFID_READER_ADAPTERS": '{"r":"simulator"}', "MQTT_MAX_PAYLOAD_BYTES": "1024"})
        self.assertEqual(settings.reader_adapters, {"r": "simulator"})
        for env in ({"RFID_READER_ADAPTERS": "[]"}, {"RFID_READER_ADAPTERS": '{"r":1}'},
                    {"MQTT_MAX_PAYLOAD_BYTES": "0"}, {"EZ700_TIMESTAMP_FORMAT": "auto"}):
            with self.assertRaises(ValueError):
                Settings.from_env(env)

    def test_simulator_invalid_signal_and_deep_json(self):
        settings = replace(self.settings, normalization_adapter="simulator")
        payload = {"tag": "tag", "port": 1, "observed_at": "2026-09-07T13:00:00Z"}
        for signal in (None, {}, {"value": 1, "unit": "dBm"}, {"value": -38, "unit": "auto"},
                       {"value": True, "unit": "dBm"}, {"value": "-38", "unit": "dBm"}):
            self.assertIsNone(self.build(payload | {"signal": signal}, settings)["canonical_event"])
        raw = b'{"extra":' + b'[' * 80 + b'0' + b']' * 80 + b'}'
        event = self.build(raw)
        self.assertIsNone(event["payload_json"])
        self.assertIsNotNone(event["parse_error"])

    def test_receiver_continues_and_logs_no_payload(self):
        with TemporaryDirectory() as directory, patch("rfid_ingestion.mqtt_client.create_client"):
            path = Path(directory) / "audit.jsonl"
            receiver = MqttReceiver(self.settings, JsonlEventStore(path),
                                    Mock(persist=Mock(return_value=PersistenceResult("inserted", 1))))
            receiver.client.ack.return_value = 0
            raws = [b'{"private":"DO-NOT-LOG",', b'\xff', b'{}',
                    b'{"extra":"\\ud800"}', FIXTURE.read_bytes()]
            with self.assertLogs("rfid_ingestion.mqtt_client") as logs:
                for raw in raws:
                    receiver._on_message(None, None, Mock(topic=reading_topic(self.reader), qos=1, retain=False, payload=raw))
            self.assertFalse(receiver.failed.is_set())
            events = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(events), len(raws))
            self.assertIsNotNone(events[-1]["canonical_event"])
            self.assertNotIn("DO-NOT-LOG", str(logs.output))
            self.assertNotIn(self.payload["epc"], str(logs.output))
            self.assertIn('"result": "accepted"', logs.output[-1])
