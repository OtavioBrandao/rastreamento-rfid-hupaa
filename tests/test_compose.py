from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("docker"), "exige Docker Compose")
class ComposeConfigurationTests(unittest.TestCase):
    def compose_config(self, profile: str, env_file: str) -> dict:
        environment = os.environ.copy()
        environment.update(
            {
                "COMPOSE_PROJECT_NAME": "rfid-compose-test",
                "DATABASE_URL": "",
                "MQTT_HOST": "endpoint.example.invalid",
                "MQTT_USERNAME": "synthetic-user",
                "MQTT_PASSWORD": "synthetic-password",
                "MQTT_CLIENT_ID": "synthetic-client",
            }
        )
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                env_file,
                "--profile",
                profile,
                "config",
                "--format",
                "json",
            ],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def test_local_profile_has_healthy_dependencies_and_internal_dns(self) -> None:
        config = self.compose_config("local", ".env.local.example")
        services = config["services"]

        self.assertEqual(
            set(services),
            {"postgres", "mosquitto", "migrate-local", "ingestor-local"},
        )
        self.assertIn("pg_isready", " ".join(services["postgres"]["healthcheck"]["test"]))
        self.assertIn("mosquitto_sub", services["mosquitto"]["healthcheck"]["test"])
        self.assertEqual(
            services["migrate-local"]["depends_on"]["postgres"]["condition"],
            "service_healthy",
        )
        self.assertEqual(
            services["ingestor-local"]["depends_on"]["mosquitto"]["condition"],
            "service_healthy",
        )
        self.assertEqual(
            services["ingestor-local"]["depends_on"]["migrate-local"]["condition"],
            "service_completed_successfully",
        )
        self.assertEqual(services["ingestor-local"]["environment"]["MQTT_HOST"], "mosquitto")
        self.assertIn("@postgres:5432/", services["migrate-local"]["environment"]["DATABASE_URL"])
        self.assertEqual(services["ingestor-local"]["user"], "1000:1000")
        self.assertIn("postgres_data", config["volumes"])
        self.assertIn("mosquitto_data", config["volumes"])
        self.assertIn(
            "mosquitto_data",
            services["mosquitto"]["volumes"][1]["source"],
        )
        self.assertIn("rfid-dev", config["networks"])

    def test_managed_profile_does_not_start_local_infrastructure(self) -> None:
        config = self.compose_config("managed", ".env.cloud.example")
        services = config["services"]

        self.assertEqual(set(services), {"migrate-managed", "ingestor-managed"})
        self.assertNotIn("postgres", services)
        self.assertNotIn("mosquitto", services)
        self.assertEqual(
            services["ingestor-managed"]["depends_on"]["migrate-managed"]["condition"],
            "service_completed_successfully",
        )
        self.assertEqual(services["migrate-managed"]["environment"]["DATABASE_URL"], "")
        self.assertEqual(services["ingestor-managed"]["environment"]["MQTT_MODE"], "cloud")


if __name__ == "__main__":
    unittest.main()
