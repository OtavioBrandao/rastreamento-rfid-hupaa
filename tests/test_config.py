from __future__ import annotations

from pathlib import Path
import unittest

from rfid_ingestion.config import Settings


class SettingsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        settings = Settings.from_env({})

        self.assertEqual(settings.mqtt_host, "127.0.0.1")
        self.assertEqual(settings.mqtt_port, 1883)
        self.assertEqual(settings.mqtt_topic, "rfid/+/tags")
        self.assertEqual(settings.events_file, Path("data/raw_events.jsonl"))
        self.assertEqual(settings.log_level, "INFO")

    def test_all_settings_can_come_from_environment(self) -> None:
        settings = Settings.from_env(
            {
                "MQTT_HOST": "192.0.2.10",
                "MQTT_PORT": "2883",
                "MQTT_TOPIC": "#",
                "MQTT_USERNAME": "usuario-teste",
                "MQTT_PASSWORD": "valor-nao-real",
                "MQTT_CLIENT_ID": "receiver-test",
                "MQTT_QOS": "2",
                "EVENTS_FILE": "tmp/events.jsonl",
                "LOG_LEVEL": "debug",
            }
        )

        self.assertEqual(settings.mqtt_host, "192.0.2.10")
        self.assertEqual(settings.mqtt_port, 2883)
        self.assertEqual(settings.mqtt_topic, "#")
        self.assertEqual(settings.mqtt_username, "usuario-teste")
        self.assertEqual(settings.mqtt_password, "valor-nao-real")
        self.assertEqual(settings.mqtt_client_id, "receiver-test")
        self.assertEqual(settings.mqtt_qos, 2)
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


if __name__ == "__main__":
    unittest.main()
