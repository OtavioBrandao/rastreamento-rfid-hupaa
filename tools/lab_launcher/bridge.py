"""Bridge MQTT local → HiveMQ Cloud para leitores sem suporte a TLS."""

from __future__ import annotations

import socket
import time
from pathlib import Path

from dotenv import dotenv_values

from .config import ROOT
from .docker_env import compose

SERVICO = "mqtt-bridge"


def perfil_bridge(reader_id: str, topico: str, valores: dict[str, str],
                  arquivo: Path | None) -> dict[str, str]:
    """Monta as variáveis da bridge com a credencial de publicação do leitor.

    A credencial vem de ``.env.cloud.<reader_id>`` (ou ``arquivo``) e precisa ser
    separada da credencial do ingestor, com tópico exato igual ao do leitor.
    """
    arquivo = arquivo or ROOT / "config" / "environments" / f".env.cloud.{reader_id}"
    if not arquivo.is_file():
        raise ValueError(f"bridge exige a credencial MQTT do leitor em {arquivo}")
    perfil = {chave: valor for chave, valor in dotenv_values(arquivo).items()
              if valor is not None}
    if not perfil.get("MQTT_USERNAME") or not perfil.get("MQTT_PASSWORD"):
        raise ValueError(f"{arquivo.name} exige MQTT_USERNAME e MQTT_PASSWORD")
    if perfil["MQTT_USERNAME"] == valores.get("MQTT_USERNAME"):
        raise ValueError("a bridge deve usar a credencial do leitor, separada do ingestor")
    if perfil.get("MQTT_TOPIC", topico) != topico:
        raise ValueError(f"{arquivo.name} publica em {perfil['MQTT_TOPIC']}, mas o leitor "
                         f"{reader_id} usa {topico}")
    print(f"Credencial MQTT da bridge: {arquivo.name}")
    return {
        "BRIDGE_REMOTE_HOST": perfil.get("MQTT_HOST") or valores["MQTT_HOST"],
        "BRIDGE_REMOTE_PORT": perfil.get("MQTT_PORT") or valores.get("MQTT_PORT", "8883"),
        "BRIDGE_REMOTE_USERNAME": perfil["MQTT_USERNAME"],
        "BRIDGE_REMOTE_PASSWORD": perfil["MQTT_PASSWORD"],
        "BRIDGE_REMOTE_CLIENT_ID": f"easy-bridge-{reader_id}",
        "BRIDGE_TOPIC": topico,
    }


def aguardar_conexao(arquivo: Path, ambiente: dict[str, str],
                     timeout: float = 30.0) -> None:
    """Espera a bridge publicar o estado ``1`` (conectada ao HiveMQ Cloud) localmente."""
    topico = f"$SYS/broker/connection/{ambiente['BRIDGE_REMOTE_CLIENT_ID']}/state"
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        try:
            estado = compose(arquivo, "managed", "exec", "-T", SERVICO, "mosquitto_sub",
                             "-h", "127.0.0.1", "-t", topico, "-C", "1", "-W", "3",
                             env=ambiente)
        except RuntimeError:
            estado = ""
        if estado.strip() == "1":
            return
        time.sleep(2)
    raise TimeoutError("a bridge não conectou ao HiveMQ Cloud; veja os logs do serviço "
                       f"{SERVICO} (credencial, ACL ou acesso à porta 8883)")


def ip_local() -> str:
    """Endereço IPv4 de saída do notebook, para configurar a URL do leitor."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("192.0.2.1", 9))
            return sock.getsockname()[0]
        except OSError:
            return "<IP-do-notebook>"
