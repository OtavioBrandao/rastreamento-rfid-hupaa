"""Publicador de heartbeat do contrato do software para ensaios controlados.

Não detecta saúde de hardware: envia o estado explicitamente escolhido pelo
operador. Use credencial restrita ao tópico exato, separada do ingestor.
"""

import argparse
import json
import time
from datetime import datetime, timezone
from threading import Event

import paho.mqtt.client as mqtt
from dotenv import dotenv_values

from rfid_ingestion.config import Settings
from rfid_ingestion.connection import create_client
from rfid_ingestion.reader_status import StatusPolicy, validate_heartbeat_topic
from tools.lab_launcher.synthetic import topico_sintetico


def main() -> int:
    """Publica até Ctrl+C; timeout e falhas não expõem parâmetros de conexão."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--reader-id", required=True)
    parser.add_argument("--portal-id", default="portal-01")
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--status", choices=("online", "degradado"), default="online")
    args = parser.parse_args()
    client = None
    try:
        config = {key: value for key, value in dotenv_values(args.env_file).items() if value is not None}
        if not config:
            raise ValueError("Perfil vazio ou inexistente")
        policy = StatusPolicy.from_env(config)
        if not 0 < args.interval < policy.degraded_after:
            raise ValueError("Intervalo deve ser positivo e menor que o limite de degradação")
        reading = topico_sintetico(config, args.reader_id, args.portal_id)
        topic = reading.removesuffix("readings") + "heartbeat"
        validate_heartbeat_topic(topic)
        settings = Settings.from_env(dict(config, MQTT_CLIENT_ID=f"heartbeat-{args.reader_id}"))
        client = create_client(settings)
        connected = Event()
        accepted = []

        def on_connect(_client, _userdata, _flags, reason, _properties):
            """Sinaliza CONNACK sem registrar broker, usuário ou senha."""
            accepted.append(not reason.is_failure)
            connected.set()

        client.on_connect = on_connect
        client.connect(settings.mqtt_host, settings.mqtt_port, settings.mqtt_keepalive)
        client.loop_start()
        if not connected.wait(10) or not accepted[0]:
            raise RuntimeError("Conexão não confirmada")
        print("Heartbeat de demonstração ativo; Ctrl+C encerra.", flush=True)
        while True:
            result = client.publish(topic, json.dumps({"status": args.status,
                                    "sent_at": datetime.now(timezone.utc).isoformat()}), qos=1, retain=False)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError("Publicação recusada")
            result.wait_for_publish(timeout=10)
            if not result.is_published():
                raise RuntimeError("PUBACK não recebido")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError, RuntimeError):
        print("Heartbeat interrompido. Confira perfil, limites, conexão e ACL do tópico.")
        return 1
    finally:
        if client is not None:
            client.disconnect()
            client.loop_stop()


if __name__ == "__main__":
    raise SystemExit(main())
