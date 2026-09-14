"""Integração opt-in com Mosquitto real: RUN_MQTT_INTEGRATION=1."""

import json
import os
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from rfid_ingestion.config import Settings
from rfid_ingestion.connection import create_client
from rfid_ingestion.mqtt_client import MqttReceiver
from rfid_ingestion.persistence import JsonlEventStore
from rfid_ingestion.verification import run_simulator


@unittest.skipUnless(os.getenv("RUN_MQTT_INTEGRATION") == "1", "exige Mosquitto local explícito")
class PipelineIntegrationTests(unittest.TestCase):
    def test_different_adapters_equivalent_readings_and_redelivery(self):
        suffix = uuid.uuid4().hex[:8]
        topic = f"easy/test/hupaa/{suffix}/+/readings"
        settings = Settings(mqtt_port=int(os.getenv("TEST_MQTT_PORT", "1883")),
                            mqtt_topic=topic, mqtt_client_id=f"normalize-{suffix}",
                            ez700_timestamp_format="epoch_ms", reader_adapters={"sim": "simulator"})
        ez = json.loads(Path("tests/fixtures/identix/tag-read.json").read_bytes())
        ez["readerid"] = "ez"
        sim = {"tag": ez["epc"], "port": ez["antenna"], "signal": {"value": ez["rssi"], "unit": "unknown"},
               "observed_at": "2021-09-27T13:16:35.291-03:00", "reader_id": "sim"}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            receiver = MqttReceiver(settings, JsonlEventStore(path))
            clients = []
            try:
                receiver.start()
                for name in ("ez", "sim"):
                    client = create_client(Settings(mqtt_client_id=f"{name}-{suffix}"))
                    client.connect(settings.mqtt_host, settings.mqtt_port)
                    client.loop_start()
                    clients.append(client)
                def publish(pair):
                    index, payload = pair
                    destination = topic.replace("+", ("ez", "sim")[index])
                    for _ in range(2):
                        message = clients[index].publish(destination, json.dumps(payload), qos=1, retain=False)
                        message.wait_for_publish(timeout=5)
                        self.assertTrue(message.is_published())
                with ThreadPoolExecutor(max_workers=2) as pool:
                    list(pool.map(publish, enumerate((ez, sim))))
                deadline = time.monotonic() + 5
                events = []
                while time.monotonic() < deadline:
                    events = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
                    if len(events) == 4:
                        break
                    time.sleep(.05)
                self.assertEqual(len(events), 4)
                canonical = [event["canonical_event"] for event in events]
                self.assertTrue(all(canonical))
                self.assertEqual({event["reader_id"] for event in canonical}, {"ez", "sim"})
                self.assertEqual(len({event["event_id"] for event in canonical}), 2)
                for field in ("epc", "antenna", "timestamp", "rssi"):
                    self.assertEqual(len({event[field] for event in canonical}), 1, field)
                self.assertFalse(receiver.failed.is_set())
            finally:
                for client in clients:
                    client.disconnect()
                    client.loop_stop()
                receiver.stop()

    def test_two_publishers_valid_invalid_and_jsonl(self):
        suffix = uuid.uuid4().hex[:8]
        env = dict(MQTT_MODE="local", MQTT_HOST="127.0.0.1", MQTT_PORT=os.getenv("TEST_MQTT_PORT", "1883"),
                   MQTT_TLS_ENABLED="false", MQTT_TOPIC=f"easy/test/hupaa/{suffix}/+/readings",
                   MQTT_CLIENT_ID=f"ingestor-{suffix}", EZ700_TIMESTAMP_FORMAT="epoch_ms")
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
                self.assertEqual(sum(e["canonical_event"] is not None for e in events), 40)
                self.assertEqual({e["topic"] for e in events}, {e["MQTT_TOPIC"] for e in publishers})
                self.assertTrue(all(e["qos"] == 1 and e["retain"] is False for e in events))
                self.assertFalse(receiver.failed.is_set())
            finally:
                receiver.stop()
