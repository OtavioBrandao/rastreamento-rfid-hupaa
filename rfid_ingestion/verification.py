"""Roteiro reproduzível com simuladores ou coleta de campo, sem segredos no relatório."""

import argparse
import json
import math
import os
import socket
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

import paho.mqtt.client as mqtt

from .config import Settings
from .connection import create_client, tls_context
from .logging_config import configure_logging
from .mqtt_client import MqttReceiver
from .persistence import JsonlEventStore


def read_environment(path: str) -> dict[str, str]:
    """Lê atribuições literais; não executa shell nem expande segredos."""
    result = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.replace("_", "").isalnum():
            raise ValueError("Arquivo de ambiente inválido")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key] = value
    return result


def probe(settings: Settings, operation: str, topic: str | None = None) -> str:
    """Exige negativa explícita do broker; timeout nunca comprova autenticação/ACL."""
    client = create_client(settings, protocol=mqtt.MQTTv5)
    done = Event()
    result = ["inconclusivo"]

    def finish(code, expected):
        result[0] = "validado" if code.value in expected else "falhou"
        done.set()

    def connected(c, _u, _f, code, _p):
        if operation == "invalid-auth":
            finish(code, (134, 135))
        elif code.is_failure:
            result[0] = "falhou"
            done.set()
        elif operation == "publish":
            c.publish(topic, '{"probe":"acl"}', qos=1, retain=False)
        else:
            c.subscribe(topic, qos=1)

    client.on_connect = connected
    client.on_publish = lambda c, u, mid, code, p: finish(code, (135,))
    client.on_subscribe = lambda c, u, mid, codes, p: finish(codes[0], (135,))

    def disconnected(c, u, flags, code, p):
        if not done.is_set() and operation != "invalid-auth" and code.value == 135:
            finish(code, (135,))

    client.on_disconnect = disconnected
    try:
        client.connect(settings.mqtt_host, settings.mqtt_port, settings.mqtt_keepalive)
        client.loop_start()
        done.wait(10)
    except (OSError, ValueError, RuntimeError):
        result[0] = "inconclusivo"
    finally:
        client.disconnect()
        client.loop_stop()
    return result[0]


def run_simulator(source: dict[str, str], count: int, interval: float, invalid=None, timestamp=None) -> int:
    # Não herdar credenciais MQTT de outro perfil.
    environment = {k: v for k, v in os.environ.items() if not k.startswith("MQTT_")}
    environment.update(source)
    command = [sys.executable, "-m", "rfid_ingestion.simulator", "--reader-id",
               source["MQTT_TOPIC"].split("/")[4], "--count", str(count),
               "--interval", str(interval)]
    if invalid:
        command.extend(["--invalid", invalid])
    if timestamp:
        command.extend(["--timestamp", timestamp])
    return subprocess.run(command, env=environment, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=30 + count * (interval + 10)).returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--publisher-env", action="append", default=[])
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--interval", type=float, default=0.1)
    parser.add_argument("--network", required=True, help="Rótulo não secreto da rede do ingestor")
    parser.add_argument("--security", action="store_true", help="Testar credencial inválida e ACL MQTT 5")
    parser.add_argument("--expected-reader", action="append", help="Leitor lógico esperado na coleta; repetir para dois")
    parser.add_argument("--report", default="data/verification.json")
    args = parser.parse_args(argv)
    if not math.isfinite(args.seconds) or not math.isfinite(args.interval) or args.seconds <= 0 or args.count < 1 or args.interval < 0:
        parser.error("Duração, quantidade e intervalo inválidos")
    report = {"date_utc": datetime.now(timezone.utc).isoformat(), "network": args.network,
              "steps": {}, "physical_validation": "pendente", "different_networks": "pendente"}
    steps = report["steps"]
    receiver = None
    secrets = []
    stage = "configuration"
    try:
        sources = [read_environment(path) for path in [args.env_file, *args.publisher_env]]
        secrets = [s[k] for s in sources for k in ("MQTT_PASSWORD", "MQTT_USERNAME") if s.get(k)]
        configure_logging("INFO", secrets)
        profiles = [Settings.from_env(source) for source in sources]
        settings, publishers = profiles[0], profiles[1:]
        if args.security and (settings.mqtt_mode != "cloud" or len(publishers) != 2):
            raise ValueError("Segurança externa exige cloud e dois perfis publicadores")
        if args.security and mqtt.topic_matches_sub(settings.mqtt_topic, "easy/acl-denied/other/other/other/readings"):
            raise ValueError("Para testar ACL do ingestor, restrinja o filtro ao ambiente/site")
        if publishers:
            if len(publishers) != 2 or len({p.mqtt_client_id for p in profiles}) != 3:
                raise ValueError("Exige dois publicadores e três Client IDs distintos")
            if len({p.mqtt_topic for p in publishers}) != 2:
                raise ValueError("Exige tópicos distintos")
            if settings.mqtt_mode == "cloud" and len({p.mqtt_username for p in profiles}) != 3:
                raise ValueError("Exige credenciais distintas")
            from .topics import validate_topic
            for publisher in publishers:
                validate_topic(publisher.mqtt_topic)
                if (publisher.mqtt_host, publisher.mqtt_port, publisher.mqtt_tls_enabled, publisher.mqtt_mode) != (
                        settings.mqtt_host, settings.mqtt_port, settings.mqtt_tls_enabled, settings.mqtt_mode):
                    raise ValueError("Perfis devem apontar para o mesmo broker e modo")
                if not mqtt.topic_matches_sub(settings.mqtt_topic, publisher.mqtt_topic):
                    raise ValueError("Filtro não cobre publicadores")
        steps[stage] = "validado"
        report.update(mode=settings.mqtt_mode,
                      source="simuladores" if publishers else "coleta externa; origem a confirmar",
                      client_ids_configured=[p.mqtt_client_id for p in profiles])
        stage = "dns"
        socket.getaddrinfo(settings.mqtt_host, settings.mqtt_port, type=socket.SOCK_STREAM)
        steps[stage] = "validado"
        stage = "tls"
        if settings.mqtt_tls_enabled:
            with socket.create_connection((settings.mqtt_host, settings.mqtt_port), timeout=10) as raw:
                with tls_context(settings).wrap_socket(raw, server_hostname=settings.mqtt_host):
                    pass
            steps[stage] = "validado"
        else:
            steps[stage] = "não executado; modo local sem TLS"
        # Arquivo novo por execução: não confundir evidências de sessões anteriores.
        output = Path("data") / f"verification-{uuid.uuid4().hex}.jsonl"
        report["events_file"] = str(output)
        stage = "connection_subscription"
        receiver = MqttReceiver(settings, JsonlEventStore(output))
        receiver.start()
        steps[stage] = "validado"
        started = time.monotonic()
        marker = str(time.time_ns())
        stage = "delivery_jsonl"
        if publishers:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda source: run_simulator(source, args.count, args.interval, timestamp=marker), sources[1:]))
            if any(results):
                raise RuntimeError("Simulador falhou")
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline:
                events = [json.loads(line) for line in output.read_text().splitlines()] if output.exists() else []
                if all(sum(e["topic"] == p.mqtt_topic and isinstance(e["payload_json"], dict)
                           and e["payload_json"].get("timestamp") == marker for e in events) >= args.count for p in publishers):
                    break
                time.sleep(0.1)
        else:
            receiver.failed.wait(args.seconds)
        elapsed = time.monotonic() - started
        receiver.stop()
        if receiver.failed.is_set():
            raise RuntimeError("Ingestor falhou")
        events = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()] if output.exists() else []
        valid = [e for e in events if not e["parse_error"] and not e["validation_errors"]
                 and e["qos"] == 1 and not e["retain"]]
        passed = bool(valid) and (not publishers or all(
            sum(e["topic"] == p.mqtt_topic and e["payload_json"]["timestamp"] == marker
                for e in valid) >= args.count for p in publishers))
        if args.expected_reader:
            observed = {e["topic"].split("/")[4] for e in valid}
            passed = passed and set(args.expected_reader).issubset(observed)
        steps[stage] = "validado" if passed else "falhou"
        report["received_count"] = len(events)
        report["rate_messages_per_second"] = round(len(events) / elapsed, 3)
        report["observation_seconds"] = round(elapsed, 3)
        report["counts_by_topic"] = {topic: sum(e["topic"] == topic for e in events)
                                     for topic in sorted({e["topic"] for e in events})}
        report["readings"] = [{"topic": e["topic"], "epc": e["payload_json"]["epc"],
                               "antenna": e["payload_json"]["antenna"],
                               "timestamp": e["payload_json"]["timestamp"],
                               "received_at_utc": e["received_at_utc"]} for e in valid[:100]]
        if args.security:
            stage = "security"
            steps["invalid_auth"] = probe(replace(publishers[0], mqtt_password=uuid.uuid4().hex), "invalid-auth")
            for index, publisher in enumerate(publishers):
                steps[f"reader_{index + 1}_wrong_topic"] = probe(publisher, "publish", publishers[1 - index].mqtt_topic)
                steps[f"reader_{index + 1}_subscribe"] = probe(publisher, "subscribe", publisher.mqtt_topic)
            steps["ingestor_publish"] = probe(settings, "publish", publishers[0].mqtt_topic)
            # Fora do filtro do ingestor, ainda dentro de um tópico sintaticamente válido.
            steps["ingestor_wrong_filter"] = probe(settings, "subscribe", "easy/acl-denied/other/other/other/readings")
        else:
            steps["security"] = "pendente"
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        steps[stage] = "falhou"
    finally:
        if receiver:
            receiver.stop()
        def sanitize(value):
            if isinstance(value, dict):
                return {key: sanitize(item) for key, item in value.items()}
            if isinstance(value, list):
                return [sanitize(item) for item in value]
            if isinstance(value, str):
                for secret in sorted(secrets, key=len, reverse=True):
                    value = value.replace(secret, "[REDACTED]")
            return value
        serialized = json.dumps(sanitize(report), ensure_ascii=False, indent=2)
        destination = Path(args.report)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(serialized + "\n", encoding="utf-8")
    print("Relatório gerado; etapas:", json.dumps(steps, ensure_ascii=False))
    return 1 if any(value in ("falhou", "inconclusivo") for value in steps.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
