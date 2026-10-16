#!/bin/sh
# Bridge de laboratório: recebe o leitor em MQTT sem TLS na rede local e
# repassa somente o tópico de leituras ao HiveMQ Cloud com TLS e credencial
# do leitor. A configuração com senha fica apenas dentro do contêiner.
set -eu

for var in BRIDGE_REMOTE_HOST BRIDGE_REMOTE_USERNAME BRIDGE_REMOTE_PASSWORD \
    BRIDGE_REMOTE_CLIENT_ID BRIDGE_TOPIC; do
    eval "valor=\${$var:-}"
    if [ -z "$valor" ]; then
        echo "ERRO: $var é obrigatória para a bridge MQTT." >&2
        exit 2
    fi
done

case "$BRIDGE_TOPIC" in
    *+*|*#*)
        echo "ERRO: BRIDGE_TOPIC deve ser exato, sem curingas." >&2
        exit 2
        ;;
esac

conf=/tmp/mosquitto-bridge.conf
umask 077
cat > "$conf" <<EOF
# SOMENTE LABORATÓRIO: listener local anônimo e sem TLS para o leitor.
listener 1883 0.0.0.0
allow_anonymous true
persistence false
connection_messages true
log_dest stdout
log_type error
log_type warning
log_type notice
log_type information

connection hivemq-cloud
address ${BRIDGE_REMOTE_HOST}:${BRIDGE_REMOTE_PORT:-8883}
bridge_protocol_version mqttv311
bridge_cafile /etc/ssl/certs/ca-certificates.crt
bridge_insecure false
remote_clientid ${BRIDGE_REMOTE_CLIENT_ID}
remote_username ${BRIDGE_REMOTE_USERNAME}
remote_password ${BRIDGE_REMOTE_PASSWORD}
# HiveMQ Cloud não reconhece o modo bridge privado do Mosquitto, e a ACL do
# leitor derruba a conexão em publicações fora do tópico de leituras; o estado
# da bridge (1 conectada, 0 desconectada) fica só no broker local, em
# \$SYS/broker/connection/<remote_clientid>/state.
try_private false
notifications true
notifications_local_only true
cleansession false
keepalive_interval 60
restart_timeout 5 30
topic ${BRIDGE_TOPIC} out 1
EOF

exec /usr/sbin/mosquitto -c "$conf"
