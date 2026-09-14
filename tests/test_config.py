from __future__ import annotations

import unittest
from pathlib import Path

from rfid_ingestion.config import Settings
from rfid_ingestion.verification import read_environment


class SettingsTests(unittest.TestCase):
    def test_ingestor_templates_use_supported_normalization_defaults(self):
        defaults = Settings()
        for name in (".env.example", ".env.local.example", ".env.cloud.example"):
            with self.subTest(template=name):
                source = read_environment(name)
                self.assertTrue({"MQTT_MAX_PAYLOAD_BYTES", "RFID_DEFAULT_ADAPTER",
                                 "RFID_READER_ADAPTERS", "EZ700_TIMESTAMP_FORMAT"} <= source.keys())
                if source["MQTT_MODE"] == "cloud":
                    source.update(MQTT_USERNAME="synthetic-user", MQTT_PASSWORD="synthetic-password")
                settings = Settings.from_env(source)
                self.assertEqual(settings.max_payload_bytes, defaults.max_payload_bytes)
                self.assertEqual(settings.normalization_adapter, defaults.normalization_adapter)
                self.assertEqual(settings.reader_adapters, defaults.reader_adapters)
                self.assertEqual(settings.ez700_timestamp_format, defaults.ez700_timestamp_format)
                settings = Settings.from_env(source | {"EZ700_TIMESTAMP_FORMAT": "epoch_ms",
                                                       "RFID_READER_ADAPTERS": '{"reader-02":"simulator"}'})
                self.assertEqual(settings.reader_adapters, {"reader-02": "simulator"})
                self.assertEqual(settings.ez700_timestamp_format, "epoch_ms")

    def test_defaults(self) -> None:
        settings = Settings.from_env({})

        self.assertEqual(settings.mqtt_host, "127.0.0.1")
        self.assertEqual(settings.mqtt_port, 1883)
        self.assertEqual(settings.mqtt_topic, "easy/+/+/+/+/readings")
        self.assertEqual(settings.events_file, Path("data/raw_events.jsonl"))
        self.assertEqual(settings.log_level, "INFO")

    def test_all_settings_can_come_from_environment(self) -> None:
        settings = Settings.from_env(
            {
                "MQTT_HOST": "192.168.1.10",
                "MQTT_PORT": "2883",
                "MQTT_TOPIC": "easy/dev/hupaa/+/+/readings",
                "MQTT_USERNAME": "usuario-teste",
                "MQTT_PASSWORD": "valor-nao-real",
                "MQTT_CLIENT_ID": "receiver-test",
                "MQTT_QOS": "1",
                "EVENTS_FILE": "tmp/events.jsonl",
                "LOG_LEVEL": "debug",
            }
        )

        self.assertEqual(settings.mqtt_host, "192.168.1.10")
        self.assertEqual(settings.mqtt_port, 2883)
        self.assertEqual(settings.mqtt_topic, "easy/dev/hupaa/+/+/readings")
        self.assertEqual(settings.mqtt_username, "usuario-teste")
        self.assertEqual(settings.mqtt_password, "valor-nao-real")
        self.assertEqual(settings.mqtt_client_id, "receiver-test")
        self.assertEqual(settings.mqtt_qos, 1)
        self.assertEqual(settings.events_file, Path("tmp/events.jsonl"))
        self.assertEqual(settings.log_level, "DEBUG")
        self.assertNotIn("valor-nao-real", repr(settings))

    def test_invalid_values_are_rejected(self) -> None:
        invalid_environments = (
            {"MQTT_PORT": "zero"},
            {"MQTT_PORT": "65536"},
            {"MQTT_TOPIC": ""},
            {"MQTT_QOS": "3"},
            {"EVENTS_FILE": ""},
            {"LOG_LEVEL": "VERBOSE"},
        )

        for environment in invalid_environments:
            with self.subTest(environment=environment):
                with self.assertRaises(ValueError):
                    Settings.from_env(environment)

    def test_compose_service_dns_is_allowed_only_for_local_mosquitto(self) -> None:
        settings = Settings.from_env({"MQTT_MODE": "local", "MQTT_HOST": "mosquitto"})

        self.assertEqual(settings.mqtt_host, "mosquitto")
        with self.assertRaises(ValueError):
            Settings.from_env({"MQTT_MODE": "local", "MQTT_HOST": "broker.example"})


if __name__ == "__main__":
    unittest.main()
