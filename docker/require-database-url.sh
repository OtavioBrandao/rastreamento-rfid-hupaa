#!/bin/sh
set -eu

if [ -z "${DATABASE_URL:-}" ]; then
    echo "ERRO: DATABASE_URL é obrigatória no perfil managed." >&2
    exit 2
fi

exec "$@"
