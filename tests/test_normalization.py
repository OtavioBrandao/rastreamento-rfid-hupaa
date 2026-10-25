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
from rfid_ingestion.normalization import ADAPTERS, normalize, utc_timestamp
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
        self.received_at = datetime(2026, 9, 25, 12, 30, 45, 123000, tzinfo=timezone.utc)

    def build(self, payload=None, settings=None, **kwargs):
        raw = payload if isinstance(payload, bytes) else json.dumps(self.payload if payload is None else payload).encode()
        return build_event(topic=kwargs.pop("topic", reading_topic(self.reader)), qos=1,
                           retain=False, payload=raw, settings=settings or self.settings,
                           received_at=kwargs.pop("received_at", self.received_at), **kwargs)

    def test_fixture_and_unknown_rssi(self):
        event = self.build()
        self.assertEqual(event["validation_errors"], [])
        canonical = event["canonical_event"]
        self.assertEqual(canonical["timestamp"], "2026-09-25T12:30:45.123000Z")
        self.assertIsNone(canonical["rssi"])
        self.assertEqual(canonical["metadata"]["rssi_original"], -3880)
        self.assertEqual(canonical["metadata"]["source_fields"]["tid"], self.payload["tid"])

    def test_relay_attributes_reading_to_virtual_reader_only_when_enabled(self):
        """Simulador web no HiveMQ: tópico do reader-01, leitura do leitor virtual."""
        topic = reading_topic("reader-01")
        body = {"epc": "E2804C41000000000000ABCD", "rssi": -5900, "antenna": 2,
                "timestamp": "123", "sim_reader_id": "sim-hupaa-03", "reader_id": "sim-hupaa-03"}
        relay = replace(self.settings, relay_virtual_readers=("reader-01",))
        event = self.build(body, relay, topic=topic)
        self.assertEqual(event["validation_errors"], [])
        self.assertEqual(event["reader_id"], "sim-hupaa-03")
        self.assertEqual(event["canonical_event"]["reader_id"], "sim-hupaa-03")
        self.assertEqual(event["canonical_event"]["metadata"]["relay_reader_id"], "reader-01")
        # Sem habilitação, em outro tópico ou com id não virtual: recusa, nunca vira reader-01.
        for settings, corpo, outro in ((self.settings, body, topic),
                                       (relay, body, reading_topic("reader-02")),
                                       (relay, dict(body, sim_reader_id="reader-02"), topic)):
            recusado = self.build(corpo, settings, topic=outro)
            self.assertIsNone(recusado["canonical_event"])
            self.assertTrue(any("sim_reader_id" in erro for erro in recusado["validation_errors"]))
        # Ingestor sem suporte a relay (código antigo) vê só o reader_id divergente: recusa.
        antigo = self.build({k: v for k, v in body.items() if k != "sim_reader_id"}, relay,
                            topic=topic)
        self.assertIsNone(antigo["canonical_event"])
        self.assertIn("reader_id do payload diverge do tópico", antigo["validation_errors"])
        fisico = self.build({k: v for k, v in body.items() if k not in ("sim_reader_id", "reader_id")},
                            relay, topic=topic)
        self.assertEqual(fisico["reader_id"], "reader-01")  # leitor físico segue igual

    def test_relay_is_refused_in_production(self):
        with self.assertRaisesRegex(ValueError, "RFID_RELAY_LEITORES_VIRTUAIS"):
            Settings.from_env({"RFID_RELAY_LEITORES_VIRTUAIS": "reader-01",
                               "APP_ENV": "production"}).validate()

    def test_ez700_counter_uses_receive_time_for_both_legacy_profiles(self):
        for profile in ("rfc3339", "epoch_ms", "counter"):
            for counter in ("1166264", 1166264, "1632759395291", 0, "0"):
                with self.subTest(profile=profile, counter=counter):
                    payload = {"epc": "007411B0A503007A91948576", "rssi": -5725,
                               "antenna": 1, "timestamp": counter}
                    event = self.build(payload, Settings(ez700_timestamp_format=profile),
                                       topic="easy/dev/hupaa/portal-01/reader-01/readings")
                    self.assertEqual(event["validation_errors"], [])
                    canonical = event["canonical_event"]
                    self.assertEqual(canonical["timestamp"], utc_timestamp(event["received_at_utc"]))
                    self.assertEqual(canonical["timestamp"], "2026-09-25T12:30:45.123000Z")
                    self.assertIsNone(canonical["rssi"])
                    self.assertEqual(canonical["metadata"]["rssi_original"], -5725)
                    self.assertEqual(canonical["metadata"]["rssi_unit"], "unknown")
                    self.assertEqual(canonical["metadata"]["timestamp_original"], counter)
                    self.assertEqual(canonical["metadata"]["timestamp_format"], "received_at_utc")

    def test_ez700_counter_uses_receipt_time_and_preserves_counter(self):
        payload = self.payload | {"timestamp": "1166264"}
        received_at = datetime(2026, 9, 25, 12, 30, 0, tzinfo=timezone.utc)
        settings = Settings.from_env({"EZ700_TIMESTAMP_FORMAT": "counter"})
        event = self.build(payload, settings, received_at=received_at)
        canonical = event["canonical_event"]
        self.assertEqual(canonical["timestamp"], "2026-09-25T12:30:00.000000Z")
        self.assertEqual(canonical["metadata"]["timestamp_original"], "1166264")
        self.assertEqual(canonical["metadata"]["timestamp_format"], "received_at_utc")
        later = self.build(payload, settings, received_at=received_at.replace(minute=31))
        self.assertEqual(canonical["event_id"], later["canonical_event"]["event_id"])

    def test_ez700_counter_without_receive_time_uses_current_utc(self):
        before = datetime.now(timezone.utc)
        canonical, errors, _, _ = normalize(
            self.payload, reading_topic(self.reader), FIXTURE.read_bytes(), Settings()
        )
        after = datetime.now(timezone.utc)
        self.assertEqual(errors, [])
        instant = datetime.fromisoformat(canonical["timestamp"].replace("Z", "+00:00"))
        self.assertLessEqual(before, instant)
        self.assertLessEqual(instant, after)

    def test_ez700_counter_still_validates_receive_timestamp(self):
        canonical, errors, _, _ = normalize(
            self.payload, reading_topic(self.reader), FIXTURE.read_bytes(), Settings(),
            received_at_utc="invalid",
        )
        self.assertIsNone(canonical)
        self.assertIn("RFC3339", errors[0])

    def test_ez700_simulator_numeric_clock_is_also_a_counter(self):
        with patch.dict("os.environ", {}, clear=True):
            parser = _parser()
        for options in ([], ["--format", "ez700"]):
            args = parser.parse_args(options + ["--reader-id", self.reader])
            with patch("rfid_ingestion.simulator.time.time_ns", return_value=1632759395291999999):
                payload = _payload(args)
            self.assertEqual(payload["timestamp"], "1632759395291")
            self.assertEqual(self.build(payload, Settings())["canonical_event"]["timestamp"],
                             "2026-09-25T12:30:45.123000Z")
            self.assertEqual(self.build(payload)["canonical_event"]["timestamp"],
                             "2026-09-25T12:30:45.123000Z")

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
                      "observed_at": "2026-09-25T09:30:45.123-03:00"}
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
                            "rssi": [None, "-38", True], "timestamp": [None, "", "yesterday", "2026-01-01T00:00:00", True, False, -1, 1.5, "-1", "1.5", "1e6", [], {}]}.items():
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
            self.assertIsNotNone(self.build(
                self.payload | {"timestamp": "2026-09-25T12:30:45Z"}, settings
            )["canonical_event"])
            self.assertIsNone(self.build(settings=settings)["canonical_event"])
        with patch.dict(ADAPTERS, {"new": Mock(side_effect=RuntimeError("private payload"))}):
            self.assertEqual(self.build(settings=settings)["validation_errors"], ["falha interna do adapter"])

    def test_configuration(self):
        settings = Settings.from_env({"RFID_READER_ADAPTERS": '{"r":"simulator"}', "MQTT_MAX_PAYLOAD_BYTES": "1024"})
        self.assertEqual(settings.reader_adapters, {"r": "simulator"})
        for env in ({"RFID_READER_ADAPTERS": "[]"}, {"RFID_READER_ADAPTERS": '{"r":1}'},
                    {"MQTT_MAX_PAYLOAD_BYTES": "0"}, {"EZ700_TIMESTAMP_FORMAT": "auto"}):
            with self.assertRaises(ValueError):
                Settings.from_env(env)

    def test_simulator_rejects_numeric_and_invalid_timestamps(self):
        settings = Settings(normalization_adapter="simulator")
        for timestamp in ("1166264", 1166264, None, "2026-09-25T12:30:45"):
            with self.subTest(timestamp=timestamp):
                payload = {"tag": "tag", "port": 1, "observed_at": timestamp,
                           "signal": {"value": -57.25, "unit": "dBm"}}
                self.assertIsNone(self.build(payload, settings)["canonical_event"])

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
                    receiver._flush_pending()
            self.assertFalse(receiver.failed.is_set())
            events = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(events), len(raws))
            self.assertIsNotNone(events[-1]["canonical_event"])
            self.assertNotIn("DO-NOT-LOG", str(logs.output))
            self.assertNotIn(self.payload["epc"], str(logs.output))
            self.assertIn('"result": "accepted"', logs.output[-1])
