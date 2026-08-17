#!/usr/bin/env bash

set -Eeuo pipefail
export LC_ALL=C

DEFAULT_CONNECTION="rfid-mvp-hotspot"
DEFAULT_SSID="RFID-MVP-TEST"
DEFAULT_HOST_CIDR="10.42.0.1/24"

usage() {
    cat <<'EOF'
Uso: ./start-hotspot.sh [opções]

Cria, se necessário, e ativa um perfil dedicado do NetworkManager.

Opções:
  -i, --interface NOME    Interface Wi-Fi (seleção automática se houver só uma)
  -s, --ssid NOME         SSID (padrão: RFID-MVP-TEST)
  -c, --connection NOME   Perfil (padrão: rfid-mvp-hotspot)
  -a, --host-cidr CIDR    Endereço do host (padrão: 10.42.0.1/24)
  -h, --help              Mostra esta ajuda

Um perfil existente nunca é alterado nem apagado por este script.
EOF
}

die() {
    printf '[FALHOU] %s\n' "$*" >&2
    exit 1
}

die_recreate_profile() {
    printf '[FALHOU] %s Nada foi alterado.\n' "$1" >&2
    printf '[INFO] Para recriar somente o perfil dedicado, execute manualmente:\n' >&2
    printf '  nmcli connection down id %q\n' "$CONNECTION" >&2
    printf '  nmcli connection delete id %q\n' "$CONNECTION" >&2
    printf '[INFO] Depois execute este script novamente com os valores desejados.\n' >&2
    exit 1
}

select_wifi_interface() {
    local requested=$1
    local -a interfaces=()
    local item

    mapfile -t interfaces < <(
        nmcli -t -f DEVICE,TYPE device status 2>/dev/null |
            awk -F: '$2 == "wifi" {print $1}'
    )

    if [[ -n $requested ]]; then
        for item in "${interfaces[@]}"; do
            [[ $item == "$requested" ]] && printf '%s\n' "$requested" && return 0
        done
        die "A interface '$requested' não foi identificada como Wi-Fi pelo NetworkManager."
    fi

    case ${#interfaces[@]} in
        0) die "Nenhuma interface Wi-Fi foi detectada." ;;
        1) printf '%s\n' "${interfaces[0]}" ;;
        *)
            printf '[FALHOU] Há várias interfaces Wi-Fi; escolha uma com --interface:\n' >&2
            printf '  - %s\n' "${interfaces[@]}" >&2
            exit 1
            ;;
    esac
}

INTERFACE=""
SSID=$DEFAULT_SSID
CONNECTION=$DEFAULT_CONNECTION
HOST_CIDR=$DEFAULT_HOST_CIDR
INTERFACE_EXPLICIT=0
SSID_EXPLICIT=0
CIDR_EXPLICIT=0

while (( $# > 0 )); do
    case $1 in
        -i|--interface)
            (( $# >= 2 )) || die "Falta o valor de $1."
            INTERFACE=$2
            INTERFACE_EXPLICIT=1
            shift 2
            ;;
        -s|--ssid)
            (( $# >= 2 )) || die "Falta o valor de $1."
            SSID=$2
            SSID_EXPLICIT=1
            shift 2
            ;;
        -c|--connection)
            (( $# >= 2 )) || die "Falta o valor de $1."
            CONNECTION=$2
            shift 2
            ;;
        -a|--host-cidr)
            (( $# >= 2 )) || die "Falta o valor de $1."
            HOST_CIDR=$2
            CIDR_EXPLICIT=1
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "Opção desconhecida: $1. Use --help."
            ;;
    esac
done

[[ $(uname -s 2>/dev/null || true) == "Linux" ]] || die "Execute este script somente no notebook Linux."
for required_command in nmcli ip python3; do
    command -v "$required_command" >/dev/null 2>&1 || die "Comando obrigatório ausente: $required_command."
done
nmcli general status >/dev/null 2>&1 || die "NetworkManager não está ativo ou não responde."
[[ -n $CONNECTION && $CONNECTION != *$'\n'* ]] || die "Nome de conexão inválido."
[[ -n $SSID && $SSID != *$'\n'* ]] || die "SSID inválido."

SSID_BYTES=$(printf '%s' "$SSID" | wc -c)
(( SSID_BYTES <= 32 )) || die "O SSID deve ter no máximo 32 bytes."

python3 - "$HOST_CIDR" <<'PY' || die "CIDR IPv4 inválido: $HOST_CIDR."
import ipaddress
import sys

value = ipaddress.ip_interface(sys.argv[1])
if value.version != 4:
    raise ValueError("IPv4 required")
PY

PROFILE_COUNT=$(nmcli -t -e no -f NAME connection show | grep -Fxc -- "$CONNECTION" || true)
(( PROFILE_COUNT <= 1 )) || die "Há mais de um perfil chamado '$CONNECTION'; use nomes únicos antes de continuar."
PROFILE_EXISTS=$PROFILE_COUNT

if (( PROFILE_EXISTS == 1 )); then
    PROFILE_TYPE=$(nmcli -g connection.type connection show "$CONNECTION" | sed -n '1p')
    PROFILE_MODE=$(nmcli -g 802-11-wireless.mode connection show "$CONNECTION" | sed -n '1p')
    PROFILE_METHOD=$(nmcli -g ipv4.method connection show "$CONNECTION" | sed -n '1p')
    PROFILE_INTERFACE=$(nmcli -g connection.interface-name connection show "$CONNECTION" | sed -n '1p')
    PROFILE_SSID=$(nmcli -g 802-11-wireless.ssid connection show "$CONNECTION" | sed -n '1p')
    PROFILE_CIDR=$(nmcli -g ipv4.addresses connection show "$CONNECTION" | sed -n '1p')
    PROFILE_BAND=$(nmcli -g 802-11-wireless.band connection show "$CONNECTION" | sed -n '1p')
    PROFILE_KEY_MGMT=$(nmcli -g 802-11-wireless-security.key-mgmt connection show "$CONNECTION" | sed -n '1p')
    PROFILE_IPV6_METHOD=$(nmcli -g ipv6.method connection show "$CONNECTION" | sed -n '1p')
    PROFILE_AUTOCONNECT=$(nmcli -g connection.autoconnect connection show "$CONNECTION" | sed -n '1p')

    [[ $PROFILE_TYPE == "802-11-wireless" ]] || die_recreate_profile "O perfil existente '$CONNECTION' não é Wi-Fi."
    [[ $PROFILE_MODE == "ap" ]] || die_recreate_profile "O perfil existente '$CONNECTION' não está em modo AP."
    [[ $PROFILE_METHOD == "shared" ]] || die_recreate_profile "O perfil existente '$CONNECTION' não usa IPv4 compartilhado."
    [[ $PROFILE_BAND == "bg" ]] || die_recreate_profile "O perfil existente '$CONNECTION' não usa a banda esperada de 2,4 GHz."
    [[ $PROFILE_KEY_MGMT == "wpa-psk" ]] || die_recreate_profile "O perfil existente '$CONNECTION' não usa WPA-PSK."
    [[ $PROFILE_IPV6_METHOD == "disabled" ]] || die_recreate_profile "O perfil existente '$CONNECTION' não tem IPv6 desativado."
    [[ $PROFILE_AUTOCONNECT == "no" ]] || die_recreate_profile "O perfil existente '$CONNECTION' tem autoconexão ativa."
    [[ -n $PROFILE_SSID && -n $PROFILE_CIDR ]] || die_recreate_profile "O perfil existente '$CONNECTION' está incompleto."

    if (( INTERFACE_EXPLICIT == 1 )) && [[ -n $PROFILE_INTERFACE && $PROFILE_INTERFACE != "$INTERFACE" ]]; then
        die_recreate_profile "O perfil existente usa '$PROFILE_INTERFACE', diferente de '$INTERFACE'."
    fi
    if (( SSID_EXPLICIT == 1 )) && [[ $PROFILE_SSID != "$SSID" ]]; then
        die_recreate_profile "O perfil existente usa o SSID '$PROFILE_SSID', diferente do valor solicitado."
    fi
    if (( CIDR_EXPLICIT == 1 )) && [[ $PROFILE_CIDR != "$HOST_CIDR" ]]; then
        die_recreate_profile "O perfil existente usa '$PROFILE_CIDR', diferente do CIDR solicitado."
    fi

    [[ -n $PROFILE_INTERFACE ]] && INTERFACE=$PROFILE_INTERFACE
    INTERFACE=$(select_wifi_interface "$INTERFACE")

    printf '[INFO] Perfil dedicado existente encontrado; ele não será modificado nem apagado.\n'
    printf '[INFO] Configuração existente: interface=%s, SSID=%s, IPv4=%s.\n' "$INTERFACE" "$PROFILE_SSID" "$PROFILE_CIDR"
    printf '[INFO] Para recriar: nmcli connection down id %q\n' "$CONNECTION"
    printf '[INFO] Depois execute manualmente: nmcli connection delete id %q\n' "$CONNECTION"
    printf '[INFO] Por fim, execute este script novamente com os valores desejados.\n'
else
    INTERFACE=$(select_wifi_interface "$INTERFACE")
fi

NM_AP_SUPPORT=$(nmcli -g WIFI-PROPERTIES.AP device show "$INTERFACE" 2>/dev/null || true)
[[ ${NM_AP_SUPPORT,,} == "yes" ]] || die "O NetworkManager não confirma suporte a hotspot/AP em '$INTERFACE'. Execute check-capabilities.sh."

printf '[AVISO] Ativar o hotspot pode desconectar o notebook da conexão Wi-Fi atual.\n'
printf '[INFO] O experimento é local e não requer acesso à internet.\n'

CREATED_PROFILE=0
ACTIVATED=0
rollback_new_profile() {
    if (( CREATED_PROFILE == 1 && ACTIVATED == 0 )); then
        printf '[INFO] A ativação falhou; removendo somente o perfil novo e incompleto %q.\n' "$CONNECTION" >&2
        nmcli connection delete "$CONNECTION" >/dev/null 2>&1 ||
            printf '[AVISO] Não foi possível remover o perfil novo. Revise-o manualmente com nmcli.\n' >&2
    fi
}
trap rollback_new_profile EXIT

if (( PROFILE_EXISTS == 0 )); then
    [[ -t 0 ]] || die "A criação do perfil requer um terminal interativo para ler a senha com segurança."
    printf 'Senha WPA do hotspot (8–63 caracteres, ou 64 dígitos hexadecimais): ' >&2
    IFS= read -r -s HOTSPOT_PASSWORD
    printf '\n' >&2

    PASSWORD_LENGTH=${#HOTSPOT_PASSWORD}
    if (( PASSWORD_LENGTH == 64 )) && [[ $HOTSPOT_PASSWORD =~ ^[[:xdigit:]]{64}$ ]]; then
        :
    elif [[ $HOTSPOT_PASSWORD =~ ^[[:print:]]{8,63}$ ]]; then
        :
    else
        unset HOTSPOT_PASSWORD
        die "A senha WPA deve ter de 8 a 63 caracteres ASCII imprimíveis ou exatamente 64 dígitos hexadecimais."
    fi

    if ! nmcli connection add \
        type wifi \
        ifname "$INTERFACE" \
        con-name "$CONNECTION" \
        autoconnect no \
        ssid "$SSID" \
        802-11-wireless.mode ap \
        802-11-wireless.band bg \
        802-11-wireless-security.key-mgmt wpa-psk \
        802-11-wireless-security.psk "$HOTSPOT_PASSWORD" \
        ipv4.method shared \
        ipv4.addresses "$HOST_CIDR" \
        ipv6.method disabled >/dev/null 2>&1; then
        unset HOTSPOT_PASSWORD
        die "Não foi possível criar o perfil dedicado; nenhuma conexão existente foi removida."
    fi
    unset HOTSPOT_PASSWORD
    CREATED_PROFILE=1
    printf '[PASSOU] Perfil dedicado criado com autoconexão desativada.\n'
fi

if ! nmcli connection up id "$CONNECTION" ifname "$INTERFACE"; then
    die "Não foi possível ativar '$CONNECTION'. Consulte o diagnóstico acima."
fi

ACTIVATED=1
trap - EXIT
printf '[PASSOU] Hotspot %q ativo na interface %s.\n' "$CONNECTION" "$INTERFACE"
printf '[INFO] Execute ./serve-test-page.sh em outro terminal para iniciar o teste HTTP.\n'
