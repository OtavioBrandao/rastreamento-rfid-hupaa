#!/usr/bin/env bash

set -euo pipefail
export LC_ALL=C

DEFAULT_CONNECTION="rfid-mvp-hotspot"

usage() {
    cat <<'EOF'
Uso: ./stop-hotspot.sh [NOME_DA_CONEXAO]
       ./stop-hotspot.sh --connection NOME_DA_CONEXAO

Desativa somente o perfil indicado. O perfil não é excluído e nenhuma outra
conexão é modificada. O padrão é rfid-mvp-hotspot.
EOF
}

CONNECTION=$DEFAULT_CONNECTION
case $# in
    0) ;;
    1)
        case $1 in
            -h|--help) usage; exit 0 ;;
            -*) printf '[FALHOU] Opção desconhecida: %s\n' "$1" >&2; exit 2 ;;
            *) CONNECTION=$1 ;;
        esac
        ;;
    2)
        [[ $1 == "--connection" || $1 == "-c" ]] || {
            usage >&2
            exit 2
        }
        CONNECTION=$2
        ;;
    *) usage >&2; exit 2 ;;
esac

[[ -n $CONNECTION && $CONNECTION != *$'\n'* ]] || {
    printf '[FALHOU] Nome de conexão inválido.\n' >&2
    exit 2
}
command -v nmcli >/dev/null 2>&1 || {
    printf '[FALHOU] nmcli não está disponível.\n' >&2
    exit 1
}
nmcli general status >/dev/null 2>&1 || {
    printf '[FALHOU] NetworkManager não está ativo ou não responde.\n' >&2
    exit 1
}

PROFILE_COUNT=$(nmcli -t -e no -f NAME connection show | grep -Fxc -- "$CONNECTION" || true)
if (( PROFILE_COUNT == 0 )); then
    printf '[INFO] O perfil %q não existe; nada foi alterado.\n' "$CONNECTION"
    exit 0
fi
(( PROFILE_COUNT == 1 )) || {
    printf '[FALHOU] Há mais de um perfil chamado %q; nenhum foi desativado.\n' "$CONNECTION" >&2
    exit 1
}

PROFILE_UUID=$(nmcli -g connection.uuid connection show "$CONNECTION" | sed -n '1p')
if ! nmcli -t -f UUID connection show --active | grep -Fqx "$PROFILE_UUID"; then
    printf '[PASSOU] O perfil %q já está inativo.\n' "$CONNECTION"
    exit 0
fi

nmcli connection down id "$CONNECTION"
printf '[PASSOU] Perfil %q desativado. Ele foi preservado para reutilização.\n' "$CONNECTION"
