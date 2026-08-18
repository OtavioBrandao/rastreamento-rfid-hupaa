#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
COMPOSE_PROJECT="rfid-mvp-smoke"
TEMP_DIR=$(mktemp -d)
EVENTS_FILE="$TEMP_DIR/events.jsonl"
RECEIVER_LOG="$TEMP_DIR/receiver.log"
RECEIVER_PID=""

cleanup() {
    if [[ -n $RECEIVER_PID ]] && kill -0 "$RECEIVER_PID" 2>/dev/null; then
        kill -INT "$RECEIVER_PID" 2>/dev/null || true
        wait "$RECEIVER_PID" 2>/dev/null || true
    fi
    docker compose -p "$COMPOSE_PROJECT" -f "$ROOT_DIR/compose.yaml" down \
        --remove-orphans >/dev/null 2>&1 || true
    rm -f -- "$EVENTS_FILE" "$RECEIVER_LOG"
    rmdir -- "$TEMP_DIR" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM

fail() {
    printf '[FALHOU] %s\n' "$1" >&2
    if [[ -s $RECEIVER_LOG ]]; then
        printf '%s\n' '--- log do receptor ---' >&2
        sed -n '1,120p' "$RECEIVER_LOG" >&2
    fi
    exit 1
}

command -v docker >/dev/null 2>&1 || fail "Docker não está disponível."
command -v python3 >/dev/null 2>&1 || fail "python3 não está disponível."
docker compose version >/dev/null 2>&1 || fail "Docker Compose não está disponível."
python3 -c 'import paho.mqtt.client' >/dev/null 2>&1 ||
    fail "Instale requirements.txt no ambiente Python antes do smoke test."

docker compose -p "$COMPOSE_PROJECT" -f "$ROOT_DIR/compose.yaml" up -d ||
    fail "Não foi possível iniciar o Mosquitto. Verifique se a porta 1883 está livre."

BROKER_READY=0
for _attempt in {1..30}; do
    if python3 - <<'PY'
import socket

with socket.create_connection(("127.0.0.1", 1883), timeout=1):
    pass
PY
    then
        BROKER_READY=1
        break
    fi
    sleep 1
done
(( BROKER_READY == 1 )) || fail "Mosquitto não abriu a porta 1883."

(
    cd -- "$ROOT_DIR"
    export MQTT_HOST=127.0.0.1
    export MQTT_PORT=1883
    export MQTT_TOPIC='rfid/+/tags'
    export MQTT_CLIENT_ID=rfid-mvp-smoke-receiver
    export EVENTS_FILE
    export LOG_LEVEL=INFO
    exec python3 -m rfid_ingestion >"$RECEIVER_LOG" 2>&1
) &
RECEIVER_PID=$!

SUBSCRIPTION_READY=0
for _attempt in {1..20}; do
    if grep -Fq 'Assinatura ativa' "$RECEIVER_LOG" 2>/dev/null; then
        SUBSCRIPTION_READY=1
        break
    fi
    kill -0 "$RECEIVER_PID" 2>/dev/null || fail "O receptor encerrou antes de assinar o tópico."
    sleep 1
done
(( SUBSCRIPTION_READY == 1 )) || fail "O receptor não confirmou a assinatura MQTT."

(
    cd -- "$ROOT_DIR"
    MQTT_HOST=127.0.0.1 MQTT_PORT=1883 \
        python3 -m rfid_ingestion.simulator \
        --reader-id smoke-reader \
        --topic rfid/smoke-reader/tags
) || fail "O simulador não conseguiu publicar."

EVENT_RECEIVED=0
for _attempt in {1..10}; do
    if [[ -s $EVENTS_FILE ]] && python3 - "$EVENTS_FILE" <<'PY'
import json
from pathlib import Path
import sys

events = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
if not any(
    (event.get("payload_json") or {}).get("readerid") == "smoke-reader"
    for event in events
):
    raise SystemExit(1)
PY
    then
        EVENT_RECEIVED=1
        break
    fi
    sleep 1
done
(( EVENT_RECEIVED == 1 )) || fail "O evento publicado não apareceu no JSONL."

printf '[PASSOU] Mosquitto, receptor, simulador e persistência JSONL integrados.\n'
