#!/usr/bin/env bash

set -euo pipefail
export LC_ALL=C

CONNECTION="rfid-mvp-hotspot"
PORT=8000

usage() {
    cat <<'EOF'
Uso: ./hotspot-status.sh [opções]

Opções:
  -c, --connection NOME   Perfil a consultar (padrão: rfid-mvp-hotspot)
  -p, --port PORTA        Porta esperada do servidor (padrão: 8000)
  -h, --help              Mostra esta ajuda

O script não consulta nem exibe segredos salvos.
EOF
}

die() { printf '[FALHOU] %s\n' "$*" >&2; exit 1; }

while (( $# > 0 )); do
    case $1 in
        -c|--connection)
            (( $# >= 2 )) || die "Falta o valor de $1."
            CONNECTION=$2
            shift 2
            ;;
        -p|--port)
            (( $# >= 2 )) || die "Falta o valor de $1."
            PORT=$2
            shift 2
            ;;
        -h|--help) usage; exit 0 ;;
        *) die "Opção desconhecida: $1. Use --help." ;;
    esac
done

[[ $PORT =~ ^[0-9]+$ ]] && (( PORT >= 1 && PORT <= 65535 )) || die "Porta inválida: $PORT."
command -v nmcli >/dev/null 2>&1 || die "nmcli não está disponível."
command -v ip >/dev/null 2>&1 || die "ip não está disponível."
nmcli general status >/dev/null 2>&1 || die "NetworkManager não está ativo ou não responde."
[[ -n $CONNECTION && $CONNECTION != *$'\n'* ]] || die "Nome de conexão inválido."

printf 'Perfil consultado: %s\n' "$CONNECTION"
PROFILE_COUNT=$(nmcli -t -e no -f NAME connection show | grep -Fxc -- "$CONNECTION" || true)
if (( PROFILE_COUNT == 0 )); then
    printf 'Perfil existente: não\n'
    printf 'Perfil ativo: não\n'
    printf '[AVISO] Crie o perfil com ./start-hotspot.sh.\n'
    exit 0
fi
(( PROFILE_COUNT == 1 )) || die "Há mais de um perfil com esse nome; use nomes únicos para obter um estado inequívoco."
printf 'Perfil existente: sim\n'

PROFILE_UUID=$(nmcli -g connection.uuid connection show "$CONNECTION" | sed -n '1p')
INTERFACE=""
if ACTIVE_ROW=$(nmcli -t -f UUID,DEVICE connection show --active | awk -F: -v uuid="$PROFILE_UUID" '$1 == uuid && !found {print; found=1}'); [[ -n $ACTIVE_ROW ]]; then
    printf 'Perfil ativo: sim\n'
    INTERFACE=${ACTIVE_ROW#*:}
else
    printf 'Perfil ativo: não\n'
    INTERFACE=$(nmcli -g connection.interface-name connection show "$CONNECTION" | sed -n '1p')
fi

[[ -n $INTERFACE ]] && printf 'Interface Wi-Fi: %s\n' "$INTERFACE" || printf 'Interface Wi-Fi: não definida\n'

ASSIGNED_CIDRS=()
if [[ -n $INTERFACE ]]; then
    mapfile -t ASSIGNED_CIDRS < <(ip -4 -o address show dev "$INTERFACE" scope global 2>/dev/null | awk '{print $4}')
fi
CONFIGURED_CIDR=""
if (( ${#ASSIGNED_CIDRS[@]} == 0 )); then
    CONFIGURED_CIDR=$(nmcli -g ipv4.addresses connection show "$CONNECTION" | sed -n '1p')
fi

if (( ${#ASSIGNED_CIDRS[@]} > 0 )); then
    printf 'IPv4 atribuído ao host: %s\n' "${ASSIGNED_CIDRS[*]}"
    HOST_IP=${ASSIGNED_CIDRS[0]%/*}
    printf 'URL esperada: http://%s:%s\n' "$HOST_IP" "$PORT"
elif [[ -n $CONFIGURED_CIDR ]]; then
    printf 'IPv4 atribuído ao host: indisponível\n'
    printf 'IPv4 configurado no perfil: %s\n' "$CONFIGURED_CIDR"
    HOST_IP=${CONFIGURED_CIDR%/*}
    printf 'URL esperada após ativação: http://%s:%s\n' "$HOST_IP" "$PORT"
else
    printf 'IPv4 atribuído ao host: não disponível\n'
    printf 'URL esperada: indisponível até o host receber um IPv4\n'
fi

CLIENT_IPS=()
if [[ -n $INTERFACE ]]; then
    mapfile -t CLIENT_IPS < <(
        ip -4 neighbor show dev "$INTERFACE" 2>/dev/null |
            awk '$0 !~ /FAILED|INCOMPLETE/ {print $1}' |
            sort -u
    )
fi

if (( ${#CLIENT_IPS[@]} > 0 )); then
    printf 'Clientes IPv4 visíveis (MAC omitido):\n'
    printf '  - %s\n' "${CLIENT_IPS[@]}"
else
    printf 'Clientes IPv4 visíveis: nenhum\n'
    printf '[AVISO] A tabela de vizinhos pode ficar vazia até o cliente trocar tráfego com o notebook.\n'
fi
