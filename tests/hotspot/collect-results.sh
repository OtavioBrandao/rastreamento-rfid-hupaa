#!/usr/bin/env bash

set -euo pipefail
export LC_ALL=C
umask 077

CONNECTION="rfid-mvp-hotspot"
INTERFACE=""
TEST_STATUS="pendente"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
RESULTS_DIR="$SCRIPT_DIR/results"

usage() {
    cat <<'EOF'
Uso: ./collect-results.sh [opções]

Opções:
  -c, --connection NOME   Perfil do hotspot (padrão: rfid-mvp-hotspot)
  -i, --interface NOME    Interface Wi-Fi, se não puder ser inferida
  -s, --status ESTADO     pendente, sucesso ou falha (padrão: pendente)
  -h, --help              Mostra esta ajuda

Gera um Markdown sanitizado em results/. Revise o arquivo antes de
compartilhá-lo ou adicioná-lo manualmente ao Git.
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
        -i|--interface)
            (( $# >= 2 )) || die "Falta o valor de $1."
            INTERFACE=$2
            shift 2
            ;;
        -s|--status)
            (( $# >= 2 )) || die "Falta o valor de $1."
            TEST_STATUS=${2,,}
            shift 2
            ;;
        -h|--help) usage; exit 0 ;;
        *) die "Opção desconhecida: $1. Use --help." ;;
    esac
done

case $TEST_STATUS in
    pendente|sucesso|falha) ;;
    *) die "Status inválido. Use pendente, sucesso ou falha." ;;
esac

for required_command in nmcli ip; do
    command -v "$required_command" >/dev/null 2>&1 || die "Comando obrigatório ausente: $required_command."
done
nmcli general status >/dev/null 2>&1 || die "NetworkManager não está ativo ou não responde."
[[ -n $CONNECTION && $CONNECTION != *$'\n'* ]] || die "Nome de conexão inválido."
[[ $INTERFACE != *$'\n'* ]] || die "Nome de interface inválido."
mkdir -p -- "$RESULTS_DIR"

PROFILE_EXISTS="não"
PROFILE_ACTIVE="não"
ACTIVE_CONNECTION="nenhuma"
HOST_CIDR="indisponível"
AP_CAPABILITY="desconhecida"

PROFILE_COUNT=$(nmcli -t -e no -f NAME connection show | grep -Fxc -- "$CONNECTION" || true)
(( PROFILE_COUNT <= 1 )) || die "Há mais de um perfil chamado '$CONNECTION'; use nomes únicos antes de coletar."
if (( PROFILE_COUNT == 1 )); then
    PROFILE_EXISTS="sim"
    PROFILE_UUID=$(nmcli -g connection.uuid connection show "$CONNECTION" | sed -n '1p')
    ACTIVE_ROW=$(nmcli -t -f UUID,DEVICE connection show --active | awk -F: -v uuid="$PROFILE_UUID" '$1 == uuid && !found {print; found=1}')
    if [[ -n $ACTIVE_ROW ]]; then
        PROFILE_ACTIVE="sim"
        ACTIVE_CONNECTION=$CONNECTION
        [[ -n $INTERFACE ]] || INTERFACE=${ACTIVE_ROW#*:}
    fi
    [[ -n $INTERFACE ]] || INTERFACE=$(nmcli -g connection.interface-name connection show "$CONNECTION" | sed -n '1p')
fi

if [[ -n $INTERFACE ]]; then
    DETECTED_CIDR=$(ip -4 -o address show dev "$INTERFACE" scope global 2>/dev/null | awk 'NR == 1 {print $4}')
    [[ -n $DETECTED_CIDR ]] && HOST_CIDR=$DETECTED_CIDR

    NM_AP=$(nmcli -g WIFI-PROPERTIES.AP device show "$INTERFACE" 2>/dev/null || true)
    case ${NM_AP,,} in
        yes) AP_CAPABILITY="suportado pelo NetworkManager" ;;
        no) AP_CAPABILITY="não suportado pelo NetworkManager" ;;
    esac

    if command -v iw >/dev/null 2>&1; then
        WIPHY=$(iw dev "$INTERFACE" info 2>/dev/null | awk '$1 == "wiphy" && !found {print "phy" $2; found=1}')
        if [[ -n $WIPHY ]] && iw phy "$WIPHY" info 2>/dev/null | awk '
            /Supported interface modes:/ {in_modes=1; next}
            in_modes && /^[[:space:]]+\*/ {
                if ($2 == "AP") found=1
                next
            }
            in_modes {in_modes=0}
            END {exit found ? 0 : 1}
        '; then
            AP_CAPABILITY="$AP_CAPABILITY; modo AP anunciado pelo iw"
        fi
    fi
fi

CLIENT_IPS=()
if [[ -n $INTERFACE ]]; then
    mapfile -t CLIENT_IPS < <(
        ip -4 neighbor show dev "$INTERFACE" 2>/dev/null |
            awk '$0 !~ /FAILED|INCOMPLETE/ {print $1}' |
            sort -u
    )
fi

OS_NAME=$(awk -F= '$1 == "PRETTY_NAME" {sub(/^"/, "", $2); sub(/"$/, "", $2); print $2; exit}' /etc/os-release 2>/dev/null || true)
[[ -n $OS_NAME ]] || OS_NAME=$(uname -srm)
NM_VERSION=$(nmcli --version 2>/dev/null | sed -n '1p')
COLLECTED_AT=$(date --iso-8601=seconds)
FILE_STAMP=$(date -u +%Y%m%d-%H%M%S)
RESULT_FILE="$RESULTS_DIR/hotspot-validation-$FILE_STAMP.md"

{
    printf '# Resultado sanitizado — hotspot local\n\n'
    printf -- '- Data e hora: `%s`\n' "$COLLECTED_AT"
    printf -- '- Sistema operacional: `%s`\n' "$OS_NAME"
    printf -- '- NetworkManager: `%s`\n' "$NM_VERSION"
    printf -- '- Capacidade AP: `%s`\n' "$AP_CAPABILITY"
    printf -- '- Perfil esperado: `%s`\n' "$CONNECTION"
    printf -- '- Perfil existente: `%s`\n' "$PROFILE_EXISTS"
    printf -- '- Perfil ativo: `%s`\n' "$PROFILE_ACTIVE"
    printf -- '- Conexão ativa do experimento: `%s`\n' "$ACTIVE_CONNECTION"
    printf -- '- Interface do hotspot: `%s`\n' "${INTERFACE:-indisponível}"
    printf -- '- IPv4 do host: `%s`\n' "$HOST_CIDR"
    if (( ${#CLIENT_IPS[@]} > 0 )); then
        printf -- '- IPs de clientes visíveis (endereços MAC omitidos): `%s`\n' "${CLIENT_IPS[*]}"
    else
        printf -- '- IPs de clientes visíveis: `nenhum`\n'
    fi
    printf -- '- Status básico informado pelo operador: `%s`\n' "$TEST_STATUS"
    printf '\n## Observação\n\n'
    printf 'Este relatório omite senhas, tokens, credenciais, hostname e endereços MAC. '
    printf 'Revise-o antes de compartilhar ou adicionar manualmente ao Git.\n'
} > "$RESULT_FILE"

printf '[PASSOU] Resultado sanitizado criado em: %s\n' "$RESULT_FILE"
printf '[AVISO] O arquivo é ignorado pelo Git por padrão; revise-o antes de qualquer commit manual.\n'
