#!/usr/bin/env bash
# Ubuntu 24.04; preserva os brokers de outros projetos Compose.
set -Eeuo pipefail
ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
COMPOSE_PROJECT="rfid-smoke-$$"
export MQTT_BIND_ADDRESS=127.0.0.1
export MQTT_LOCAL_PORT=${TEST_MQTT_PORT:-18884}
export TEST_MQTT_PORT=$MQTT_LOCAL_PORT
cleanup() {
    docker compose -p "$COMPOSE_PROJECT" -f "$ROOT_DIR/compose.yaml" \
        --profile local down >/dev/null 2>&1 || true
}
trap cleanup EXIT
cd -- "$ROOT_DIR"
python3 -c 'import paho.mqtt.client'
docker compose -p "$COMPOSE_PROJECT" --profile local up -d --wait mosquitto
python3 - <<'PY'
import os
import socket
import time
for attempt in range(30):
    try:
        with socket.create_connection(("127.0.0.1", int(os.environ["TEST_MQTT_PORT"])), timeout=1):
            break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit("[FALHOU] Mosquitto não abriu a porta de teste")
PY
RUN_MQTT_INTEGRATION=1 python3 -m unittest discover -s tests -v
printf '[PASSOU] Dois simuladores, mensagens inválidas e JSONL no Mosquitto local.\n'
