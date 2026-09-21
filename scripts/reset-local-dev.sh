#!/usr/bin/env bash
# Ubuntu 24.04. Remove somente recursos Docker do projeto local conhecido.
set -Eeuo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PROJECT_NAME=${COMPOSE_PROJECT_NAME:-rfid-hospital-local}

if [[ "$PROJECT_NAME" != "rfid-hospital-local" \
    && "$PROJECT_NAME" != rfid-iss003-smoke-* \
    && "$PROJECT_NAME" != rfid-iss007-smoke-* ]]; then
    printf 'ERRO: projeto recusado pelo reset local: %s\n' "$PROJECT_NAME" >&2
    exit 2
fi

if [[ "${CONFIRM_RESET_LOCAL:-}" != "APAGAR" ]]; then
    printf 'Operação destrutiva recusada. Use CONFIRM_RESET_LOCAL=APAGAR make reset-local.\n' >&2
    exit 2
fi

cd -- "$ROOT_DIR"
docker compose --project-name "$PROJECT_NAME" --profile local \
    down --volumes --remove-orphans
printf 'Estado Docker local removido: projeto=%s, incluindo volumes PostgreSQL/Mosquitto.\n' \
    "$PROJECT_NAME"
