#!/usr/bin/env bash

set -euo pipefail

PORT=${1:-8000}
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PUBLIC_DIR="$SCRIPT_DIR/public"

usage() {
    cat <<'EOF'
Uso: ./serve-test-page.sh [PORTA]

Serve tests/hotspot/public em 0.0.0.0. A porta padrão é 8000.
Este é apenas um servidor de teste de conectividade, não o backend do MVP.
EOF
}

if [[ $PORT == "--help" || $PORT == "-h" ]]; then
    usage
    exit 0
fi
(( $# <= 1 )) || { usage >&2; exit 2; }
[[ $PORT =~ ^[0-9]+$ ]] && (( PORT >= 1 && PORT <= 65535 )) || {
    printf '[FALHOU] Porta inválida: %s.\n' "$PORT" >&2
    exit 2
}
command -v python3 >/dev/null 2>&1 || {
    printf '[FALHOU] python3 não está disponível.\n' >&2
    exit 1
}
[[ -d $PUBLIC_DIR ]] || {
    printf '[FALHOU] Diretório público não encontrado: %s\n' "$PUBLIC_DIR" >&2
    exit 1
}

if ! python3 - "$PORT" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
PY
then
    printf '[FALHOU] A porta %s já está em uso ou não pode ser aberta.\n' "$PORT" >&2
    exit 1
fi

HOST_IP=${RFID_HOTSPOT_HOST_IP:-10.42.0.1}
printf '[INFO] URL esperada no cliente: http://%s:%s\n' "$HOST_IP" "$PORT"
printf '[INFO] Servidor temporário de conectividade; não é o futuro backend do MVP.\n'
printf '[INFO] Pressione Ctrl+C para encerrar.\n'

cd -- "$PUBLIC_DIR"
exec python3 -m http.server "$PORT" --bind 0.0.0.0
