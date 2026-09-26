"""Publica leituras sintéticas no contrato MQTT existente."""

from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import datetime, timezone
from threading import Event
from uuid import uuid4

import paho.mqtt.client as mqtt

from rfid_ingestion.config import Settings
from rfid_ingestion.connection import create_client
from rfid_ingestion.topics import reading_topic


def publicar(config: dict[str, str], reader_id: str, *, epcs: list[str],
             passagem: bool, intervalo: float, portal_id: str = "portal-01") -> int:
    if not math.isfinite(intervalo) or intervalo < 0:
        raise ValueError("intervalo deve ser finito e não negativo")
    if not epcs or any(not re.fullmatch(r"(?:[0-9A-Fa-f]{2}){4,32}", epc) for epc in epcs):
        raise ValueError("informe EPCs hexadecimais válidos")
    assinatura = config.get("MQTT_TOPIC", "easy/dev/hupaa/+/+/readings").split("/")
    ambiente = assinatura[1] if len(assinatura) == 6 and assinatura[1] != "+" else "dev"
    site = assinatura[2] if len(assinatura) == 6 and assinatura[2] != "+" else "hupaa"
    topic = reading_topic(reader_id, ambiente, site, portal_id)
    source = dict(config, MQTT_TOPIC=topic, MQTT_CLIENT_ID=f"lab-publisher-{uuid4().hex[:12]}")
    settings = Settings.from_env(source)
    if not mqtt.topic_matches_sub(config.get("MQTT_TOPIC", "easy/dev/hupaa/+/+/readings"),
                                  topic):
        raise ValueError("tópico sintético não corresponde à assinatura do ingestor")
    client = create_client(settings)
    conectado = Event()
    erro = []

    def on_connect(_client, _userdata, _flags, reason_code, _properties):
        if reason_code.is_failure:
            erro.append("conexão MQTT recusada")
        conectado.set()

    client.on_connect = on_connect
    try:
        client.connect(settings.mqtt_host, settings.mqtt_port, settings.mqtt_keepalive)
        client.loop_start()
        if not conectado.wait(10) or erro:
            raise RuntimeError("broker MQTT indisponível")
        total = 0
        for epc in epcs:
            for porta in ((1, 2) if passagem else (1,)):
                payload = {
                    "epc": epc,
                    "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    "rssi": -3880,
                    "antenna": porta,
                    "readerid": reader_id,
                }
                result = client.publish(topic, json.dumps(payload), qos=1)
                result.wait_for_publish(timeout=10)
                if not result.is_published():
                    raise RuntimeError("broker não confirmou a leitura sintética")
                total += 1
                print(f"Leitura {total}: EPC {epc}, porta {porta}, tópico {topic}", flush=True)
                if passagem and porta == 1:
                    time.sleep(intervalo)
        return total
    finally:
        client.disconnect()
        client.loop_stop()


def epcs_padrao(quantidade: int) -> list[str]:
    if quantidade < 1:
        raise ValueError("quantidade deve ser positiva")
    return ["E280" + os.urandom(10).hex().upper() for _ in range(quantidade)]
