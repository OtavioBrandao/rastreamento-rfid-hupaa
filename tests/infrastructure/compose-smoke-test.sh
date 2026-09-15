#!/usr/bin/env bash
# Ubuntu 24.04; valida o perfil local completo em um projeto descartável.
set -Eeuo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
COMPOSE_PROJECT="rfid-iss003-smoke-$$"
OUTPUT_BASENAME="iss003-smoke-$$.jsonl"
OUTPUT_FILE="$ROOT_DIR/data/$OUTPUT_BASENAME"
PYTHON_BIN=${PYTHON_BIN:-python3}

export COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT"
export MQTT_BIND_ADDRESS=127.0.0.1
export MQTT_LOCAL_PORT=${TEST_MQTT_PORT:-18884}
export POSTGRES_BIND_ADDRESS=127.0.0.1
export POSTGRES_PORT=${TEST_POSTGRES_PORT:-15432}
export POSTGRES_DB=rfid_smoke
export POSTGRES_USER=rfid_smoke
export POSTGRES_PASSWORD=rfid_smoke_only
export EVENTS_FILE="data/$OUTPUT_BASENAME"
export EZ700_TIMESTAMP_FORMAT=epoch_ms

compose() {
    docker compose --project-name "$COMPOSE_PROJECT" \
        --env-file "$ROOT_DIR/.env.local.example" --profile local "$@"
}

cleanup() {
    CONFIRM_RESET_LOCAL=APAGAR bash "$ROOT_DIR/scripts/reset-local-dev.sh" \
        >/dev/null 2>&1 || true
    rm -f -- "$OUTPUT_FILE"
}
trap cleanup EXIT

cd -- "$ROOT_DIR"
rm -f -- "$OUTPUT_FILE"

compose config --quiet
compose up -d --build --wait
compose exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"

migration_output=$(compose run --rm migrate-local alembic current 2>&1)
grep -q 'da436f7c75b3 (head)' <<<"$migration_output"
compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tAc "SELECT to_regclass('public.leituras_brutas') IS NOT NULL" | grep -qx t
compose ps --services --filter status=running | grep -qx ingestor-local

# Topologia explícita apenas no banco descartável deste teste.
compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    < tests/fixtures/topology.sql

compose run --rm --no-deps \
    -e MQTT_CLIENT_ID=easy-smoke-simulator \
    -e MQTT_TOPIC=easy/dev/hupaa/portal-01/reader-01/readings \
    ingestor-local python -m rfid_ingestion.simulator \
    --reader-id reader-01 --count 1 --interval 0

for _attempt in $(seq 1 30); do
    [[ -s "$OUTPUT_FILE" ]] && break
    sleep 1
done

"$PYTHON_BIN" - "$OUTPUT_FILE" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit("JSONL do smoke test não foi criado")
events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
if len(events) != 1 or events[0]["parse_error"] is not None or events[0]["canonical_event"] is None:
    raise SystemExit("JSONL do smoke test não contém exatamente um evento válido")
if events[0]["topic"] != "easy/dev/hupaa/portal-01/reader-01/readings":
    raise SystemExit("JSONL do smoke test contém tópico inesperado")
PY

compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tAc "SELECT count(*) FROM leituras_brutas" | grep -qx 1

CONFIRM_RESET_LOCAL=APAGAR bash "$ROOT_DIR/scripts/reset-local-dev.sh"
if docker volume inspect "${COMPOSE_PROJECT}_postgres_data" >/dev/null 2>&1; then
    printf 'FALHOU: volume PostgreSQL local sobreviveu ao reset.\n' >&2
    exit 1
fi

compose up -d --build --wait
migration_output=$(compose run --rm migrate-local alembic current 2>&1)
grep -q 'da436f7c75b3 (head)' <<<"$migration_output"

printf '[PASSOU] Postgres/Mosquitto saudáveis, migration no head, ingestor e MQTT→JSONL/PostgreSQL.\n'
printf '[PASSOU] Reset local removeu o volume e a migration recriou o schema vazio.\n'
