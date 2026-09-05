import io
import json
import logging
from pathlib import Path
import ssl
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from rfid_ingestion.config import Settings
from rfid_ingestion.connection import create_client, tls_context
from rfid_ingestion.logging_config import SecretFilter
from rfid_ingestion.mqtt_client import MqttReceiver
from rfid_ingestion.parsing import build_event
from rfid_ingestion.simulator import _parser, _payload, _validate, main
from rfid_ingestion.topics import reading_topic, validate_topic
from rfid_ingestion.verification import read_environment, probe, main as verify


def cloud_env():
    return dict(MQTT_MODE="cloud", MQTT_HOST="example.hivemq.cloud",
                MQTT_USERNAME="synthetic-user", MQTT_PASSWORD="synthetic-secret",
                MQTT_CLIENT_ID="test-ingestor")


class ManagedMqttTests(unittest.TestCase):
    def test_cloud_requires_every_credential_field_and_explicit_id(self):
        for field in ("MQTT_HOST", "MQTT_USERNAME", "MQTT_PASSWORD", "MQTT_CLIENT_ID"):
            env = cloud_env()
            del env[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                Settings.from_env(env)

    def test_security_downgrades_and_urls_are_rejected(self):
        for changes in ({"MQTT_TLS_ENABLED": "false"}, {"MQTT_TLS_ENABLED": "yes"},
                        {"MQTT_PORT": "1883"}, {"MQTT_HOST": "mqtts://user:secret@host"},
                        {"MQTT_MODE": "local"}, {"MQTT_KEEPALIVE": "0"},
                        {"MQTT_QOS": "0"}, {"MQTT_CLIENT_ID": "bad\nclient"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                Settings.from_env(cloud_env() | changes)

    def test_tls_context_checks_certificate_and_hostname(self):
        settings = Settings.from_env(cloud_env())
        context = tls_context(settings)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(settings.mqtt_port, 8883)
        with patch("rfid_ingestion.connection.mqtt.Client") as factory:
            create_client(settings)
            factory.return_value.tls_set_context.assert_called_once()
            factory.return_value.username_pw_set.assert_called_once_with("synthetic-user", "synthetic-secret")
            factory.return_value.tls_insecure_set.assert_not_called()

    def test_local_client_does_not_enable_tls_or_auth(self):
        with patch("rfid_ingestion.connection.mqtt.Client") as factory:
            create_client(Settings.from_env({}))
            factory.return_value.tls_set_context.assert_not_called()
            factory.return_value.username_pw_set.assert_not_called()

    def test_private_lan_and_credential_pair(self):
        for host in ("localhost", "127.0.0.1", "192.168.1.20", "10.0.0.2", "::1"):
            self.assertEqual(Settings.from_env({"MQTT_HOST": host}).mqtt_host, host)
        for env in ({"MQTT_HOST": "8.8.8.8"}, {"MQTT_USERNAME": "only"}, {"MQTT_PASSWORD": "only"}):
            with self.assertRaises(ValueError):
                Settings.from_env(env)

    def test_topics_and_legacy_rejection(self):
        self.assertEqual(reading_topic("reader-02"), "easy/dev/hupaa/portal-01/reader-02/readings")
        for topic in ("rfid/reader-01/tags", "easy/dev/hupaa/portal-01/+/readings",
                      "easy/dev/hupaa//reader-01/readings", "easy/dev/hupaa/p/r/readings/extra"):
            with self.assertRaises(ValueError):
                validate_topic(topic)
        validate_topic("easy/+/+/+/+/readings", subscription=True)

    def test_fixture_payload_is_preserved_and_validated(self):
        raw = Path("tests/fixtures/identix/tag-read.json").read_bytes()
        event = build_event(topic=reading_topic("reader-01"), qos=1, retain=False, payload=raw)
        self.assertEqual(event["payload_json"], json.loads(raw))
        self.assertEqual(event["payload_original"], raw.decode())
        self.assertEqual(event["validation_errors"], [])
        for raw in (b'{}', b'[]', b'{"epc":"a","timestamp":"1","rssi":false,"antenna":true}'):
            event = build_event(topic=reading_topic("r"), qos=1, retain=False, payload=raw)
            self.assertTrue(event["validation_errors"])
            self.assertEqual(event["payload_original"], raw.decode())

    def test_deterministic_simulator_and_topic_mismatch(self):
        with patch.dict("os.environ", {}, clear=True):
            parser = _parser()
        args = parser.parse_args(["--reader-id", "reader-02", "--antenna", "2", "--timestamp", "123"])
        self.assertEqual(_payload(args)["timestamp"], "123")
        self.assertEqual(_payload(args)["antenna"], 2)
        self.assertIn("reader-02", _validate(args, parser))
        args.topic = reading_topic("reader-01")
        with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            _validate(args, parser)

    def test_simulator_does_not_fill_missing_cloud_host(self):
        env = cloud_env()
        del env["MQTT_HOST"]
        with patch.dict("os.environ", env, clear=True), patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            main([])

    def test_suback_required_and_refusal_is_failure(self):
        with patch("rfid_ingestion.mqtt_client.create_client"):
            receiver = MqttReceiver(Settings(), Mock())
            receiver._on_subscribe(None, None, 1, [Mock(is_failure=True)], None)
            self.assertTrue(receiver.failed.is_set())
            self.assertFalse(receiver.ready.is_set())
            receiver = MqttReceiver(Settings(), Mock())
            receiver._on_subscribe(None, None, 1, [Mock(is_failure=False, value=1)], None)
            self.assertTrue(receiver.ready.is_set())

    def test_persistence_failure_stops_receiver(self):
        with patch("rfid_ingestion.mqtt_client.create_client"):
            store = Mock()
            store.append.side_effect = OSError("synthetic-secret")
            receiver = MqttReceiver(Settings(), store)
            with self.assertLogs("rfid_ingestion.mqtt_client", level="ERROR") as captured:
                receiver._on_message(None, None, Mock(topic=reading_topic("r"), qos=1, retain=False, payload=b'{}'))
            self.assertTrue(receiver.failed.is_set())
            self.assertNotIn("synthetic-secret", str(captured.output))

    def test_redaction_and_environment_are_literal(self):
        secret = "synthetic-secret"
        record = logging.LogRecord("test", logging.INFO, "", 0, "value=%s", (secret,), None)
        SecretFilter([secret]).filter(record)
        self.assertNotIn(secret, record.getMessage())
        self.assertNotIn(secret, repr(Settings.from_env(cloud_env())))
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("MQTT_PASSWORD='literal$(echo x)'\n", encoding="utf-8")
            self.assertEqual(read_environment(str(path))["MQTT_PASSWORD"], "literal$(echo x)")

    def test_network_error_is_not_proof_of_bad_credentials(self):
        with patch("rfid_ingestion.verification.create_client") as factory:
            factory.return_value.connect.side_effect = OSError("synthetic-secret")
            self.assertEqual(probe(Settings.from_env(cloud_env()), "invalid-auth"), "inconclusivo")

    def test_auth_probe_requires_explicit_connack_denial(self):
        for code, expected in ((135, "validado"), (134, "validado"), (0, "falhou"), (136, "falhou")):
            with patch("rfid_ingestion.verification.create_client") as factory:
                client = factory.return_value
                client.loop_start.side_effect = lambda: client.on_connect(client, None, None, Mock(value=code), None)
                self.assertEqual(probe(Settings.from_env(cloud_env()), "invalid-auth"), expected)

    def test_report_marks_missing_cloud_credentials_as_failure(self):
        with TemporaryDirectory() as directory:
            profile = Path(directory) / ".env.cloud"
            report = Path(directory) / "report.json"
            profile.write_text("MQTT_MODE=cloud\n", encoding="utf-8")
            with patch("sys.stdout", io.StringIO()):
                result = verify(["--env-file", str(profile), "--network", "test",
                                 "--report", str(report)])
            self.assertEqual(result, 1)
            self.assertEqual(json.loads(report.read_text())["steps"], {"configuration": "falhou"})

    def test_report_redacts_secrets_even_with_json_escaping(self):
        secret = 'synthetic-"-secret'
        env = cloud_env() | {"MQTT_PASSWORD": secret}
        with TemporaryDirectory() as directory:
            profile = Path(directory) / ".env.cloud"
            report = Path(directory) / "report.json"
            profile.write_text("\n".join(f"{k}={v}" for k, v in env.items()), encoding="utf-8")
            with patch("rfid_ingestion.verification.socket.getaddrinfo", side_effect=OSError(secret)), patch("sys.stdout", io.StringIO()):
                result = verify(["--env-file", str(profile), "--network", secret, "--report", str(report)])
            self.assertEqual(result, 1)
            evidence = json.loads(report.read_text())
            self.assertEqual(evidence["network"], "[REDACTED]")
            self.assertEqual(evidence["steps"]["dns"], "falhou")

    def test_report_rejects_duplicate_client_ids_before_network(self):
        with TemporaryDirectory() as directory:
            profiles = []
            for index in range(3):
                path = Path(directory) / f".env.{index}"
                env = cloud_env()
                if index:
                    env["MQTT_TOPIC"] = reading_topic(f"reader-{index}")
                path.write_text("\n".join(f"{k}={v}" for k, v in env.items()), encoding="utf-8")
                profiles.append(str(path))
            with patch("rfid_ingestion.verification.socket.getaddrinfo") as dns, patch("sys.stdout", io.StringIO()):
                result = verify(["--env-file", profiles[0], "--publisher-env", profiles[1],
                                 "--publisher-env", profiles[2], "--network", "test",
                                 "--report", str(Path(directory) / "report.json")])
            self.assertEqual(result, 1)
            dns.assert_not_called()
