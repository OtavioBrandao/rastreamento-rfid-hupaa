#!/usr/bin/env bash
# Ubuntu 24.04; interrompe somente serviços de um projeto Compose descartável.
set -Eeuo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
COMPOSE_PROJECT="rfid-iss007-smoke-$$"
OUTPUT_BASENAME="iss007-smoke-$$.jsonl"
OUTPUT_FILE="$ROOT_DIR/data/$OUTPUT_BASENAME"
TOPIC=easy/dev/hupaa/portal-01/reader-01/readings

export COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT"
export MQTT_BIND_ADDRESS=127.0.0.1
export MQTT_LOCAL_PORT=${TEST_MQTT_PORT:-18885}
export POSTGRES_BIND_ADDRESS=127.0.0.1
export POSTGRES_PORT=${TEST_POSTGRES_PORT:-15433}
export POSTGRES_DB=rfid_resilience_smoke
export POSTGRES_USER=rfid_resilience_smoke
export POSTGRES_PASSWORD=rfid_resilience_smoke_only
export EVENTS_FILE="data/$OUTPUT_BASENAME"
export EZ700_TIMESTAMP_FORMAT=epoch_ms
export MQTT_RECONNECT_INITIAL_DELAY=0.2
export MQTT_RECONNECT_MAX_DELAY=1
export MQTT_RECONNECT_MULTIPLIER=2
export MQTT_RECONNECT_JITTER=0
export DB_RETRY_INITIAL_DELAY=0.2
export DB_RETRY_MAX_DELAY=1
export DB_RETRY_MULTIPLIER=2
export DB_RETRY_JITTER=0

compose() {
    docker compose -f deploy/compose.yaml --project-name "$COMPOSE_PROJECT" \
        --env-file "$ROOT_DIR/config/environments/.env.local.example" --profile local "$@"
}

cleanup() {
    CONFIRM_RESET_LOCAL=APAGAR bash "$ROOT_DIR/scripts/reset-local-dev.sh" \
        >/dev/null 2>&1 || true
    rm -f -- "$OUTPUT_FILE"
}
trap cleanup EXIT

log_count() {
    local pattern=$1
    local count
    count=$(compose logs --no-color ingestor-local 2>&1 | grep -c "$pattern" || true)
    printf '%s' "$count"
}

wait_for_log_after() {
    local pattern=$1
    local previous=$2
    local current
    for _attempt in $(seq 1 100); do
        current=$(log_count "$pattern")
        if (( current > previous )); then
            return 0
        fi
        sleep 0.2
    done
    compose logs --no-color ingestor-local >&2
    printf 'FALHOU: log não observado: %s\n' "$pattern" >&2
    return 1
}

wait_for_reading_count() {
    local expected=$1
    local observed
    for _attempt in $(seq 1 100); do
        observed=$(compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -tAc "SELECT count(*) FROM leituras_brutas" 2>/dev/null | tr -d '[:space:]' || true)
        if [[ "$observed" == "$expected" ]]; then
            return 0
        fi
        sleep 0.2
    done
    printf 'FALHOU: leituras esperadas=%s observadas=%s\n' "$expected" "${observed:-indisponível}" >&2
    return 1
}

publish() {
    local timestamp=$1
    local epc=$2
    local client_suffix=$3
    compose run --rm --no-deps \
        -e MQTT_CLIENT_ID="iss007-publisher-$client_suffix" \
        -e MQTT_TOPIC="$TOPIC" \
        ingestor-local python -m rfid_ingestion.simulator \
        --reader-id reader-01 --count 1 --interval 0 \
        --timestamp "$timestamp" --epc "$epc"
}

cd -- "$ROOT_DIR"
rm -f -- "$OUTPUT_FILE"
compose config --quiet
compose build ingestor-local
compose up -d --wait postgres
compose run --rm migrate-local alembic -c config/alembic.ini upgrade head
compose exec -T postgres psql -v ON_ERROR_STOP=1 \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" < tests/fixtures/topology.sql

# Cenário A: ingestor inicia sem broker e se recupera quando Mosquitto aparece.
compose up -d --no-deps ingestor-local
wait_for_log_after 'mqtt_reconnect_scheduled' 0
recovered_before=$(log_count 'mqtt_recovered')
compose up -d --wait mosquitto
wait_for_log_after 'mqtt_recovered' "$recovered_before"
publish 1789462800000 E280-ISS007-A a
wait_for_reading_count 1

# Cenário B: queda do broker, reconexão e restauração da assinatura.
disconnect_before=$(log_count 'mqtt_disconnected')
recovered_before=$(log_count 'mqtt_recovered')
subscription_before=$(log_count 'mqtt_subscription_restored')
compose stop -t 2 mosquitto
wait_for_log_after 'mqtt_disconnected' "$disconnect_before"
compose start mosquitto
wait_for_log_after 'mqtt_recovered' "$recovered_before"
wait_for_log_after 'mqtt_subscription_restored' "$subscription_before"
publish 1789462801000 E280-ISS007-A b
wait_for_reading_count 2

# Cenário C: falha do banco, ausência de ACK, redelivery e idempotência.
database_down_before=$(log_count 'database_unavailable')
database_recovered_before=$(log_count 'database_recovered')
compose stop -t 2 postgres
publish 1789462802000 E280-ISS007-DB db-failure
wait_for_log_after 'database_unavailable' "$database_down_before"
compose start postgres
for _attempt in $(seq 1 100); do
    compose exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        >/dev/null 2>&1 && break
    sleep 0.2
done
wait_for_log_after 'database_recovered' "$database_recovered_before"
wait_for_reading_count 3

# A mesma mensagem produz o mesmo event_id e não cria segunda linha lógica.
publish 1789462802000 E280-ISS007-DB db-duplicate
sleep 1
wait_for_reading_count 3

# Shutdown durante backoff do banco deve terminar sem aguardar o atraso total.
database_down_before=$(log_count 'database_unavailable')
shutdown_before=$(log_count 'shutdown_complete')
compose stop -t 2 postgres
publish 1789462803000 E280-ISS007-SHUTDOWN shutdown
wait_for_log_after 'database_unavailable' "$database_down_before"
compose stop -t 5 ingestor-local
wait_for_log_after 'shutdown_complete' "$shutdown_before"

grep -q '"canonical_event"' "$OUTPUT_FILE"
printf '[PASSOU] Broker inicialmente ausente recuperou com backoff e assinatura ativa.\n'
printf '[PASSOU] Reinício do Mosquitto recuperou sessão/assinatura e retomou ingestão.\n'
printf '[PASSOU] PostgreSQL indisponível não recebeu ACK; redelivery persistiu uma linha.\n'
printf '[PASSOU] event_id bloqueou duplicata e shutdown interrompeu recuperação.\n'
