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
                                 "RFID_READER_ADAPTERS", "EZ700_TIMESTAMP_FORMAT",
                                 "MQTT_RECONNECT_INITIAL_DELAY", "MQTT_RECONNECT_MAX_DELAY",
                                 "MQTT_RECONNECT_MULTIPLIER", "MQTT_RECONNECT_JITTER",
                                 "DB_RETRY_INITIAL_DELAY", "DB_RETRY_MAX_DELAY",
                                 "DB_RETRY_MULTIPLIER", "DB_RETRY_JITTER"} <= source.keys())
                self.assertTrue({"RFID_DEBOUNCE_WINDOW_MS",
                                 "RFID_OUT_OF_ORDER_TOLERANCE_MS",
                                 "RFID_PASSAGE_MAX_INTERVAL_MS"} <= source.keys())
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
        self.assertEqual(settings.mqtt_reconnect_initial_delay, 1)
        self.assertEqual(settings.mqtt_reconnect_max_delay, 30)
        self.assertEqual(settings.db_retry_jitter, 0.2)
        self.assertEqual(settings.rfid_debounce_window_ms, 250)
        self.assertEqual(settings.rfid_out_of_order_tolerance_ms, 1000)
        self.assertEqual(settings.rfid_passage_max_interval_ms, 3000)

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
                "MQTT_RECONNECT_INITIAL_DELAY": "0.5",
                "MQTT_RECONNECT_MAX_DELAY": "12",
                "MQTT_RECONNECT_MULTIPLIER": "1.5",
                "MQTT_RECONNECT_JITTER": "0.1",
                "DB_RETRY_INITIAL_DELAY": "2",
                "DB_RETRY_MAX_DELAY": "20",
                "DB_RETRY_MULTIPLIER": "3",
                "DB_RETRY_JITTER": "0.4",
                "RFID_DEBOUNCE_WINDOW_MS": "400",
                "RFID_OUT_OF_ORDER_TOLERANCE_MS": "1500",
                "RFID_PASSAGE_MAX_INTERVAL_MS": "4500",
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
        self.assertEqual(settings.mqtt_reconnect_initial_delay, 0.5)
        self.assertEqual(settings.mqtt_reconnect_max_delay, 12)
        self.assertEqual(settings.mqtt_reconnect_multiplier, 1.5)
        self.assertEqual(settings.mqtt_reconnect_jitter, 0.1)
        self.assertEqual(settings.db_retry_initial_delay, 2)
        self.assertEqual(settings.db_retry_max_delay, 20)
        self.assertEqual(settings.db_retry_multiplier, 3)
        self.assertEqual(settings.db_retry_jitter, 0.4)
        self.assertEqual(settings.rfid_debounce_window_ms, 400)
        self.assertEqual(settings.rfid_out_of_order_tolerance_ms, 1500)
        self.assertEqual(settings.rfid_passage_max_interval_ms, 4500)
        self.assertNotIn("valor-nao-real", repr(settings))

    def test_invalid_values_are_rejected(self) -> None:
        invalid_environments = (
            {"MQTT_PORT": "zero"},
            {"MQTT_PORT": "65536"},
            {"MQTT_TOPIC": ""},
            {"MQTT_QOS": "3"},
            {"EVENTS_FILE": ""},
            {"LOG_LEVEL": "VERBOSE"},
            {"MQTT_RECONNECT_INITIAL_DELAY": "0"},
            {"MQTT_RECONNECT_MAX_DELAY": "0.5"},
            {"MQTT_RECONNECT_MULTIPLIER": "0.9"},
            {"MQTT_RECONNECT_JITTER": "1.1"},
            {"DB_RETRY_JITTER": "nan"},
            {"RFID_DEBOUNCE_WINDOW_MS": "0"},
            {"RFID_DEBOUNCE_WINDOW_MS": "1.5"},
            {"RFID_OUT_OF_ORDER_TOLERANCE_MS": "-1"},
            {"RFID_OUT_OF_ORDER_TOLERANCE_MS": "late"},
            {"RFID_PASSAGE_MAX_INTERVAL_MS": "0"},
            {"RFID_PASSAGE_MAX_INTERVAL_MS": "-1"},
            {"RFID_PASSAGE_MAX_INTERVAL_MS": "late"},
            {"RFID_PASSAGE_MAX_INTERVAL_MS": "1.5"},
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
