"""Sonda curta do broker e do banco usada pelo Compose de laboratório."""

from __future__ import annotations

import os
from dataclasses import replace
from threading import Event

from sqlalchemy import text

from db.runtime import create_app_engine

from .config import Settings
from .connection import create_client


def main() -> int:
    """Executa a entrada de linha de comando de rfid_ingestion.health; devolve o código de saída quando aplicável."""
    client = None
    engine = None
    try:
        engine = create_app_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        settings = Settings.from_env()
        settings = replace(settings, mqtt_client_id=f"{settings.mqtt_client_id}-health-{os.getpid()}")
        client = create_client(settings)
        conectado = Event()
        valido = []

        def on_connect(_client, _userdata, _flags, reason_code, _properties):
            """Trata a resposta de conexão MQTT e sinaliza prontidão ou falha ao chamador."""
            valido.append(not reason_code.is_failure)
            conectado.set()

        client.on_connect = on_connect
        client.connect(settings.mqtt_host, settings.mqtt_port, settings.mqtt_keepalive)
        client.loop_start()
        return 0 if conectado.wait(5) and valido == [True] else 1
    except Exception:
        return 1
    finally:
        if client is not None:
            try:
                client.disconnect()
                client.loop_stop()
            except Exception:
                pass
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
