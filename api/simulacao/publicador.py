"""Publicação MQTT de leituras virtuais no MESMO contrato dos leitores físicos.

O payload segue o formato observado no EZ700 (`epc`, `rssi`, `antenna`,
`timestamp` contador), sem `readerid` no corpo: o leitor sai do tópico
`easy/<ambiente>/<site>/<portal>/<reader_id>/readings`, como no hardware.
Leitores DR Max virtuais usam este mesmo contrato canônico — o protocolo
físico do DR Max não foi validado e nada aqui o presume.

As credenciais ficam só no processo do servidor; o navegador nunca as vê.
"""

from __future__ import annotations

import json
import secrets
import time
from collections import deque
from threading import Event
from uuid import uuid4

import paho.mqtt.client as mqtt

from api.epc import normalizar_epc
from rfid_ingestion.config import Settings
from rfid_ingestion.connection import create_client
from rfid_ingestion.topics import reading_topic

ASSINATURA_PADRAO = "easy/dev/hupaa/+/+/readings"
LIMITE_PUBACK_S = 10.0


def _falha_puback(topic: str, desconectado: bool) -> str:
    """Monta diagnóstico de publicação sem PUBACK, distinguindo timeout de desconexão."""
    if desconectado:
        return (f"conexão MQTT encerrada antes do PUBACK para {topic}; confira se a "
                "credencial do publicador tem permissão Publish nesse tópico")
    return (f"sem PUBACK QoS 1 em {LIMITE_PUBACK_S:g} s para {topic}; confira conexão, "
            "permissão Publish e tópico da credencial do publicador")


def novo_contador(total: int) -> int:
    """Reserva um intervalo de sete dígitos para identificar este ensaio."""
    if total < 1 or total >= 9_000_000:
        raise ValueError("quantidade de mensagens excede o contador sintético de sete dígitos")
    return 1_000_000 + secrets.randbelow(9_000_000 - total)


def topico_sintetico(config: dict[str, str], reader_id: str, portal_id: str) -> str:
    """Tópico do leitor, no mesmo ambiente/site assinado pelo ingestor."""
    assinatura_texto = config.get("MQTT_TOPIC", ASSINATURA_PADRAO)
    assinatura = assinatura_texto.split("/")
    ambiente = assinatura[1] if len(assinatura) == 6 and assinatura[1] != "+" else "dev"
    site = assinatura[2] if len(assinatura) == 6 and assinatura[2] != "+" else "hupaa"
    topic = reading_topic(reader_id, ambiente, site, portal_id)
    if not mqtt.topic_matches_sub(assinatura_texto, topic):
        raise ValueError("tópico sintético não corresponde à assinatura do ingestor")
    return topic


def payload(epc: str, porta: int, rssi: int, contador: int) -> str:
    """JSON compacto na ordem observada no leitor; sem ``readerid`` no corpo."""
    return json.dumps({"epc": epc, "rssi": rssi, "antenna": porta,
                       "timestamp": str(contador)}, separators=(",", ":"))


def _dica_acl(motivo: str | None) -> str:
    """Queda logo ao publicar: quase sempre ACL do broker sem os tópicos virtuais.

    Em MQTT 3.1.1 o HiveMQ Cloud não diz o motivo: só fecha a conexão
    ("Unspecified error"). Conferido em 25/10/2026 com a credencial do
    reader-01: conectada e parada fica no ar; publicar fora do tópico dela, cai.
    """
    if motivo and any(trecho in motivo.lower() for trecho in ("authoriz", "autoriz", "unspecified")):
        return ("; provável falta de permissão: a credencial de publicação do simulador precisa "
                "publicar em easy/<ambiente>/<site>/+/+/readings no broker (ACL do HiveMQ)")
    return ""


class PublicadorMultiLeitor:
    """Uma conexão MQTT para vários leitores virtuais (um tópico por leitor).

    Publica QoS 1 sem bloquear a cada PUBACK; `conferir` falha se alguma
    mensagem esperar mais que `LIMITE_PUBACK_S` ou se a conexão cair.
    """

    def __init__(self, config: dict[str, str], *, assinatura: str, permitido: str | None = None,
                 capacidade: int = 8_000_000) -> None:
        """`assinatura` é o filtro do ingestor; `permitido`, o da ACL do publicador."""
        self.assinatura = assinatura
        self.permitido = permitido
        self.contador = novo_contador(capacidade)
        self._fim = self.contador + capacidade
        source = dict(config, MQTT_TOPIC=reading_topic("sim-validacao"),
                      MQTT_CLIENT_ID=f"simulador-web-{uuid4().hex[:12]}")
        self._settings = Settings.from_env(source)
        self._client = create_client(self._settings)
        self._conectado = Event()
        self._desconectado = Event()
        self.motivo_desconexao: str | None = None
        self._erro: list[str] = []
        self._em_voo: deque[tuple[float, str, mqtt.MQTTMessageInfo]] = deque()
        self.publicadas = 0
        self.confirmadas = 0

    @property
    def destino(self) -> str:
        """Broker de destino sem credenciais, para exibição."""
        esquema = "mqtts" if self._settings.mqtt_tls_enabled else "mqtt"
        return f"{esquema}://{self._settings.mqtt_host}:{self._settings.mqtt_port}"

    def topico(self, reader_id: str, portal_id: str) -> str:
        """Tópico do leitor virtual, conferido contra o ingestor e a ACL do publicador."""
        topico = topico_sintetico({"MQTT_TOPIC": self.assinatura}, reader_id, portal_id)
        if self.permitido and not mqtt.topic_matches_sub(self.permitido, topico):
            raise ValueError(f"o tópico {topico} não está autorizado para o publicador "
                             f"({self.permitido})")
        return topico

    def conectar(self, timeout: float = 10) -> None:
        """Conecta ao broker e espera o CONNACK."""
        def on_connect(_client, _userdata, _flags, reason_code, _properties):
            """Registra recusa de conexão e libera a espera."""
            if reason_code.is_failure:
                self._erro.append("conexão MQTT do simulador recusada; confira a credencial")
            self._conectado.set()

        def on_disconnect(_client, _userdata, _flags, reason_code, _properties):
            """Marca a desconexão (com o motivo do broker) para `conferir` falhar com diagnóstico."""
            self.motivo_desconexao = str(reason_code) if reason_code is not None else None
            self._desconectado.set()

        self._client.on_connect = on_connect
        self._client.on_disconnect = on_disconnect
        self._client.connect(self._settings.mqtt_host, self._settings.mqtt_port,
                             self._settings.mqtt_keepalive)
        self._client.loop_start()
        if not self._conectado.wait(timeout):
            raise RuntimeError("simulador não recebeu CONNACK do broker em 10 s")
        if self._erro:
            raise RuntimeError(self._erro[0])

    def emitir(self, topico: str, epc: str, porta: int, rssi: int) -> None:
        """Publica uma leitura QoS 1 no tópico do leitor virtual."""
        if self.contador >= self._fim:
            raise RuntimeError("contador sintético esgotado; reinicie a simulação")
        result = self._client.publish(
            topico, payload(normalizar_epc(epc), porta, rssi, self.contador), qos=1)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            motivo = f" (broker desconectou: {self.motivo_desconexao})" if self.motivo_desconexao else ""
            raise RuntimeError(f"MQTT não enfileirou a leitura para {topico}: "
                               f"{mqtt.error_string(result.rc)}{motivo}{_dica_acl(self.motivo_desconexao)}")
        self.contador += 1
        self.publicadas += 1
        self._em_voo.append((time.monotonic(), topico, result))

    def conferir(self) -> None:
        """Descarta confirmadas; falha na mais antiga sem PUBACK."""
        while self._em_voo and self._em_voo[0][2].is_published():
            self._em_voo.popleft()
            self.confirmadas += 1
        if not self._em_voo:
            return
        enviada_em, topico, _ = self._em_voo[0]
        if self._desconectado.is_set() or time.monotonic() - enviada_em > LIMITE_PUBACK_S:
            raise RuntimeError(_falha_puback(topico, self._desconectado.is_set()))

    @property
    def pendentes(self) -> int:
        """Publicações que ainda aguardam PUBACK."""
        return len(self._em_voo)

    def fechar(self) -> None:
        """Encerra a conexão e o loop de rede."""
        self._client.disconnect()
        self._client.loop_stop()
