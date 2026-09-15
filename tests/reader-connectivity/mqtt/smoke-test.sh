#!/usr/bin/env bash
# Ubuntu 24.04; preserva os brokers de outros projetos Compose.
set -Eeuo pipefail
ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
COMPOSE_PROJECT="rfid-smoke-$$"
PYTHON_BIN=${PYTHON_BIN:-python3}
export MQTT_BIND_ADDRESS=127.0.0.1
export MQTT_LOCAL_PORT=${TEST_MQTT_PORT:-18884}
export TEST_MQTT_PORT=$MQTT_LOCAL_PORT
export POSTGRES_BIND_ADDRESS=127.0.0.1
export POSTGRES_PORT=${TEST_POSTGRES_PORT:-15432}
export POSTGRES_USER=rfid_smoke
export POSTGRES_PASSWORD=rfid_smoke_only
export POSTGRES_DB=rfid_smoke
export TEST_DATABASE_URL="postgresql+psycopg2://$POSTGRES_USER:$POSTGRES_PASSWORD@127.0.0.1:$POSTGRES_PORT/$POSTGRES_DB"
cleanup() {
    docker compose -p "$COMPOSE_PROJECT" -f "$ROOT_DIR/compose.yaml" \
        --profile local down --volumes >/dev/null 2>&1 || true
}
trap cleanup EXIT
cd -- "$ROOT_DIR"
"$PYTHON_BIN" -c 'import paho.mqtt.client'
docker compose -p "$COMPOSE_PROJECT" --profile local up -d --wait mosquitto postgres
"$PYTHON_BIN" - <<'PY'
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
RUN_MQTT_INTEGRATION=1 "$PYTHON_BIN" -m pytest -q
printf '[PASSOU] Dois simuladores, mensagens inválidas, JSONL e PostgreSQL no Mosquitto local.\n'
