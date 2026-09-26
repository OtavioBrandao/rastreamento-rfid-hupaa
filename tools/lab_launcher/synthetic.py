"""Publica leituras sintéticas no contrato MQTT existente."""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from threading import Event
from uuid import uuid4

import paho.mqtt.client as mqtt

from api.epc import normalizar_epc
from rfid_ingestion.config import Settings
from rfid_ingestion.connection import create_client
from rfid_ingestion.topics import reading_topic


def publicar(config: dict[str, str], reader_id: str, *, epcs: list[str],
             passagem: bool, intervalo: float, portal_id: str = "portal-01",
             repeticoes: int = 3, intervalo_rajada: float = 0.08,
             timestamp_format: str = "counter") -> int:
    if (not math.isfinite(intervalo) or intervalo < 0
            or not math.isfinite(intervalo_rajada) or intervalo_rajada < 0):
        raise ValueError("intervalos devem ser finitos e não negativos")
    if repeticoes < 1:
        raise ValueError("repetições por antena devem ser positivas")
    if timestamp_format not in ("counter", "rfc3339"):
        raise ValueError("formato sintético deve ser counter ou rfc3339")
    if not epcs:
        raise ValueError("informe EPCs hexadecimais válidos")
    epcs = [normalizar_epc(epc) for epc in epcs]
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
        contador = time.monotonic_ns() // 1_000_000 % 100_000_000_000
        for epc in epcs:
            for porta in ((1, 2) if passagem else (1,)):
                for indice in range(repeticoes):
                    timestamp = (str(contador + total) if timestamp_format == "counter"
                                 else datetime.now(timezone.utc).isoformat(
                                     timespec="milliseconds"))
                    payload = {
                        "epc": epc,
                        "timestamp": timestamp,
                        "rssi": -3880,
                        "antenna": porta,
                        "readerid": reader_id,
                    }
                    result = client.publish(topic, json.dumps(payload), qos=1)
                    result.wait_for_publish(timeout=10)
                    if not result.is_published():
                        raise RuntimeError("broker não confirmou a leitura sintética")
                    total += 1
                    print(f"Leitura {total}: EPC {epc}, porta {porta}, "
                          f"rajada {indice + 1}/{repeticoes}, tópico {topic}", flush=True)
                    if indice + 1 < repeticoes:
                        time.sleep(intervalo_rajada)
                if passagem and porta == 1:
                    time.sleep(intervalo)
        return total
    finally:
        client.disconnect()
        client.loop_stop()


def epcs_padrao(quantidade: int) -> list[str]:
    if quantidade < 1:
        raise ValueError("quantidade deve ser positiva")
    if quantidade > 0xFFFFFFFFFFFF:
        raise ValueError("quantidade excede o limite de EPCs sintéticos")
    return [f"E2804C414200{indice:012X}" for indice in range(1, quantidade + 1)]
