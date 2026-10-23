"""Publica leituras sintéticas no contrato MQTT existente (scripts de galeria e ensaios)."""

from __future__ import annotations

import time
from collections import deque
from threading import Event
from uuid import uuid4

import paho.mqtt.client as mqtt

from api.epc import normalizar_epc
from api.simulacao.publicador import (
    ASSINATURA_PADRAO,
    LIMITE_PUBACK_S,
    _falha_puback,
    novo_contador,
    payload,
    topico_sintetico,
)
from rfid_ingestion.config import Settings
from rfid_ingestion.connection import create_client

# Contrato compartilhado com o simulador web (api/simulacao/publicador.py).
__all__ = ["ASSINATURA_PADRAO", "LIMITE_PUBACK_S", "Publicador", "novo_contador", "payload",
           "topico_sintetico"]


class Publicador:
    """Conexão MQTT do simulador; publica QoS 1 sem bloquear a cada PUBACK.

    As mensagens ficam em voo até o PUBACK; ``conferir`` falha se alguma
    esperar mais que ``LIMITE_PUBACK_S`` ou se a conexão cair.
    """

    def __init__(self, config: dict[str, str], reader_id: str, *,
                 portal_id: str = "portal-01", capacidade: int = 1_000_000,
                 contador_inicial: int | None = None) -> None:
        """Inicializa Publicador com as dependências e valores recebidos."""
        self.topic = topico_sintetico(config, reader_id, portal_id)
        self.contador = (novo_contador(capacidade) if contador_inicial is None
                         else contador_inicial)
        self._fim = self.contador + capacidade
        if self.contador < 1_000_000 or self._fim > 10_000_000:
            raise ValueError("intervalo do contador sintético deve ter sete dígitos")
        source = dict(config, MQTT_TOPIC=self.topic,
                      MQTT_CLIENT_ID=f"lab-simulador-{uuid4().hex[:12]}")
        self._settings = Settings.from_env(source)
        self._client = create_client(self._settings)
        self._conectado = Event()
        self._desconectado = Event()
        self._erro: list[str] = []
        self._em_voo: deque[tuple[float, mqtt.MQTTMessageInfo]] = deque()
        self.publicadas = 0
        self.confirmadas = 0

    def conectar(self, timeout: float = 10) -> None:
        """Conecta o publicador ao broker, inicia o loop de rede e espera a confirmação de conexão."""
        def on_connect(_client, _userdata, _flags, reason_code, _properties):
            """Trata a resposta de conexão MQTT e sinaliza prontidão ou falha ao chamador."""
            if reason_code.is_failure:
                self._erro.append("conexão MQTT do publicador recusada; confira a credencial")
            self._conectado.set()

        def on_disconnect(_client, _userdata, _flags, _reason_code, _properties):
            """Registra desconexão MQTT e interrompe publicação quando ela é inesperada."""
            self._desconectado.set()

        self._client.on_connect = on_connect
        self._client.on_disconnect = on_disconnect
        self._client.connect(self._settings.mqtt_host, self._settings.mqtt_port,
                             self._settings.mqtt_keepalive)
        self._client.loop_start()
        if not self._conectado.wait(timeout):
            raise RuntimeError("publicador não recebeu CONNACK do broker em 10 s")
        if self._erro:
            raise RuntimeError(self._erro[0])

    def emitir(self, epc: str, porta: int, rssi: int) -> None:
        """Publica uma leitura sintética QoS 1 e acompanha seu PUBACK sem bloquear a interface."""
        if self.contador >= self._fim:
            raise RuntimeError("contador sintético esgotado; reinicie o simulador")
        result = self._client.publish(
            self.topic, payload(normalizar_epc(epc), porta, rssi, self.contador), qos=1)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT não enfileirou a leitura para {self.topic}: "
                               f"{mqtt.error_string(result.rc)}")
        self.contador += 1
        self.publicadas += 1
        self._em_voo.append((time.monotonic(), result))
        self.conferir()

    def conferir(self) -> None:
        """Descarta mensagens confirmadas; falha na mais antiga sem PUBACK."""
        while self._em_voo and self._em_voo[0][1].is_published():
            self._em_voo.popleft()
            self.confirmadas += 1
        if not self._em_voo:
            return
        enviada_em, _ = self._em_voo[0]
        if self._desconectado.is_set() or time.monotonic() - enviada_em > LIMITE_PUBACK_S:
            raise RuntimeError(_falha_puback(self.topic, self._desconectado.is_set()))

    @property
    def pendentes(self) -> int:
        """Conta publicações QoS 1 que ainda aguardam confirmação do broker."""
        return len(self._em_voo)

    def fechar(self) -> None:
        """Encerra publicação e loop MQTT, liberando os recursos do publicador."""
        self._client.disconnect()
        self._client.loop_stop()
