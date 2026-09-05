"""Integração opt-in com Mosquitto real: RUN_MQTT_INTEGRATION=1."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
import uuid

from rfid_ingestion.config import Settings
from rfid_ingestion.mqtt_client import MqttReceiver
from rfid_ingestion.persistence import JsonlEventStore
from rfid_ingestion.verification import run_simulator


@unittest.skipUnless(os.getenv("RUN_MQTT_INTEGRATION") == "1", "exige Mosquitto local explícito")
class PipelineIntegrationTests(unittest.TestCase):
    def test_two_publishers_valid_invalid_and_jsonl(self):
        suffix = uuid.uuid4().hex[:8]
        env = dict(MQTT_MODE="local", MQTT_HOST="127.0.0.1", MQTT_PORT=os.getenv("TEST_MQTT_PORT", "1883"),
                   MQTT_TLS_ENABLED="false", MQTT_TOPIC=f"easy/test/hupaa/{suffix}/+/readings",
                   MQTT_CLIENT_ID=f"ingestor-{suffix}")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            receiver = MqttReceiver(Settings.from_env(env), JsonlEventStore(path))
            try:
                receiver.start()
                publishers = [env | dict(MQTT_CLIENT_ID=f"reader-{n}-{suffix}",
                                        MQTT_TOPIC=f"easy/test/hupaa/{suffix}/reader-{n}/readings") for n in (1, 2)]
                with ThreadPoolExecutor(max_workers=2) as pool:
                    self.assertEqual(list(pool.map(lambda e: run_simulator(e, 20, .01), publishers)), [0, 0])
                self.assertEqual(run_simulator(publishers[0], 1, 0, "json"), 0)
                self.assertEqual(run_simulator(publishers[1], 1, 0, "missing"), 0)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    events = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
                    if len(events) >= 42:
                        break
                    time.sleep(.05)
                self.assertEqual(len(events), 42)
                self.assertEqual(sum(e["parse_error"] is not None for e in events), 1)
                self.assertEqual(sum(bool(e["validation_errors"]) for e in events), 1)
                self.assertEqual({e["topic"] for e in events}, {e["MQTT_TOPIC"] for e in publishers})
                self.assertTrue(all(e["qos"] == 1 and e["retain"] is False for e in events))
                self.assertFalse(receiver.failed.is_set())
            finally:
                receiver.stop()
