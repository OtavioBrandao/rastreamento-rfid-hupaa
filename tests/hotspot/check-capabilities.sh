#!/usr/bin/env bash

set -u
export LC_ALL=C

usage() {
    cat <<'EOF'
Uso: ./check-capabilities.sh [INTERFACE_WIFI]

Verifica, sem alterar a rede, se o Ubuntu possui os recursos necessários
para executar o experimento de hotspot.
EOF
}

pass() { printf '[PASSOU] %s\n' "$*"; }
warn() { printf '[AVISO] %s\n' "$*"; }
fail() { printf '[FALHOU] %s\n' "$*" >&2; FAILURES=$((FAILURES + 1)); }

if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
    usage
    exit 0
fi

if (( $# > 1 )); then
    usage >&2
    exit 2
fi

REQUESTED_INTERFACE=${1:-}
FAILURES=0

if [[ $(uname -s 2>/dev/null || true) == "Linux" ]]; then
    pass "Sistema operacional Linux detectado."
else
    fail "Este script deve ser executado em Linux (alvo: Ubuntu 24.04)."
fi

for command_name in nmcli ip python3; do
    if command -v "$command_name" >/dev/null 2>&1; then
        pass "Comando obrigatório encontrado: $command_name."
    else
        fail "Comando obrigatório ausente: $command_name. Instale-o manualmente antes do teste."
    fi
done

if command -v iw >/dev/null 2>&1; then
    pass "Comando opcional encontrado: iw."
    HAS_IW=1
else
    warn "Comando opcional iw não encontrado; a checagem usará somente o NetworkManager."
    HAS_IW=0
fi

if command -v nmcli >/dev/null 2>&1; then
    if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager; then
        pass "NetworkManager está ativo."
    elif nmcli general status >/dev/null 2>&1; then
        pass "NetworkManager responde ao nmcli."
    else
        fail "NetworkManager não está ativo ou não responde ao nmcli."
    fi
else
    fail "Não foi possível verificar se o NetworkManager está ativo."
fi

WIFI_INTERFACES=()
if command -v nmcli >/dev/null 2>&1 && nmcli device status >/dev/null 2>&1; then
    mapfile -t WIFI_INTERFACES < <(
        nmcli -t -f DEVICE,TYPE device status 2>/dev/null |
            awk -F: '$2 == "wifi" {print $1}'
    )
fi

SELECTED_INTERFACE=""
if [[ -n $REQUESTED_INTERFACE ]]; then
    for wifi_interface in "${WIFI_INTERFACES[@]}"; do
        if [[ $wifi_interface == "$REQUESTED_INTERFACE" ]]; then
            SELECTED_INTERFACE=$REQUESTED_INTERFACE
            break
        fi
    done
    if [[ -z $SELECTED_INTERFACE ]]; then
        fail "A interface '$REQUESTED_INTERFACE' não foi identificada pelo NetworkManager como Wi-Fi."
    fi
elif (( ${#WIFI_INTERFACES[@]} == 1 )); then
    SELECTED_INTERFACE=${WIFI_INTERFACES[0]}
    pass "Única interface Wi-Fi selecionada automaticamente: $SELECTED_INTERFACE."
elif (( ${#WIFI_INTERFACES[@]} == 0 )); then
    fail "Nenhuma interface Wi-Fi foi detectada pelo NetworkManager."
else
    warn "Mais de uma interface Wi-Fi foi encontrada:"
    printf '  - %s\n' "${WIFI_INTERFACES[@]}"
    fail "Execute novamente informando uma interface: ./check-capabilities.sh INTERFACE_WIFI"
fi

if [[ -n $SELECTED_INTERFACE ]]; then
    pass "Interface Wi-Fi disponível: $SELECTED_INTERFACE."
    AP_CONFIRMED=0

    NM_AP_SUPPORT=$(nmcli -g WIFI-PROPERTIES.AP device show "$SELECTED_INTERFACE" 2>/dev/null || true)
    case ${NM_AP_SUPPORT,,} in
        yes)
            pass "NetworkManager informa suporte a hotspot/AP em $SELECTED_INTERFACE."
            AP_CONFIRMED=1
            ;;
        no)
            fail "NetworkManager informa que $SELECTED_INTERFACE não suporta hotspot/AP."
            ;;
        *)
            warn "NetworkManager não informou de forma conclusiva o suporte a hotspot/AP."
            ;;
    esac

    if (( HAS_IW == 1 )); then
        WIPHY=$(iw dev "$SELECTED_INTERFACE" info 2>/dev/null | awk '$1 == "wiphy" {print "phy" $2; exit}')
        if [[ -z $WIPHY ]]; then
            warn "O iw não conseguiu associar $SELECTED_INTERFACE a um dispositivo físico."
        elif iw phy "$WIPHY" info 2>/dev/null | awk '
            /Supported interface modes:/ {in_modes=1; next}
            in_modes && /^[[:space:]]+\*/ {
                if ($2 == "AP") found=1
                next
            }
            in_modes {in_modes=0}
            END {exit found ? 0 : 1}
        '; then
            pass "O driver também anuncia modo AP por meio do iw."
            AP_CONFIRMED=1
        else
            warn "O iw não encontrou modo AP no dispositivo de $SELECTED_INTERFACE. Confirme driver e firmware."
        fi
    fi

    if (( AP_CONFIRMED == 0 )); then
        fail "Não foi possível confirmar suporte a hotspot/AP para $SELECTED_INTERFACE."
    fi
fi

if (( FAILURES > 0 )); then
    printf '\nResultado: %d requisito(s) obrigatório(s) não atendido(s).\n' "$FAILURES" >&2
    exit 1
fi

printf '\nResultado: requisitos obrigatórios atendidos. Nenhuma configuração de rede foi alterada.\n'
