"""Detecção ilustrativa: quais antenas "enxergam" um ponto da planta.

Distância euclidiana na escala de x, com o eixo y corrigido pela proporção da
planta (mesmo critério do simulador Flet anterior), e RSSI linear entre a
antena e a borda do alcance. Não há equivalência metrológica com o hardware: é
só o gatilho que decide quando publicar uma leitura no MQTT.

Antena direcional: `orientacao` em graus no sentido da tela (0° = direita,
90° = baixo, 180° = esquerda, 270° = cima). O alcance é `alcance` na visada
direta e cai suavemente até `alcance * fator_traseiro` atrás:

    r(Δ) = alcance * (f + (1 - f) * ((1 + cos Δ) / 2) ** 2)

com Δ = ângulo entre a visada e a direção do ponto. `orientacao` nula é a
antena omnidirecional dos layouts anteriores (círculo de raio `alcance`).
O frontend (`frontend/src/services/simulacao.ts`) usa a mesma fórmula para
desenhar a cobertura e destacar a leitura.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

RSSI_PERTO = -5700
RSSI_LONGE = -6700


@dataclass(frozen=True)
class AntenaVirtual:
    """Antena posicionada, pronta para o cálculo de detecção."""

    chave: str
    reader_id: str
    porta: int
    x: float
    y: float
    alcance: float
    orientacao: float | None = None
    fator_traseiro: float = 1.0


def distancia(x1: float, y1: float, x2: float, y2: float, proporcao: float) -> float:
    """Distância na escala de x; `proporcao` = largura/altura da planta."""
    return math.hypot(x1 - x2, (y1 - y2) / proporcao)


def alcance_na_direcao(alcance: float, orientacao: float | None, fator_traseiro: float,
                       angulo: float) -> float:
    """Alcance efetivo na direção `angulo` (radianos, escala de x, y para baixo)."""
    if orientacao is None:
        return alcance
    frente = (1 + math.cos(angulo - math.radians(orientacao))) / 2
    return alcance * (fator_traseiro + (1 - fator_traseiro) * frente ** 2)


def alcance_ate(antena: AntenaVirtual, x: float, y: float, proporcao: float) -> float:
    """Alcance efetivo da antena na direção do ponto (x, y)."""
    angulo = math.atan2((y - antena.y) / proporcao, x - antena.x)
    return alcance_na_direcao(antena.alcance, antena.orientacao, antena.fator_traseiro, angulo)


def rssi(distancia_antena: float, alcance: float) -> int:
    """Linear de -5700 (sobre a antena) a -6700 (borda do alcance naquela direção)."""
    fracao = min(max(distancia_antena / alcance, 0.0), 1.0)
    return round(RSSI_PERTO + (RSSI_LONGE - RSSI_PERTO) * fracao)


def antenas_do_layout(layout: dict) -> list[AntenaVirtual]:
    """Antenas com posição; as não posicionadas não detectam nada."""
    return [
        AntenaVirtual(antena["chave"], leitor["reader_id"], antena["porta"],
                      antena["posicao"]["x"], antena["posicao"]["y"], antena["alcance"],
                      antena.get("orientacao"), antena.get("fator_traseiro", 1.0))
        for leitor in layout.get("leitores", [])
        for antena in leitor["antenas"]
        if antena.get("posicao")
    ]


def detectar(x: float, y: float, antenas: list[AntenaVirtual], proporcao: float
             ) -> list[tuple[AntenaVirtual, int]]:
    """Antenas cujo alcance (na direção do ponto) contém o ponto, com o RSSI."""
    resultado = []
    for antena in antenas:
        d = distancia(x, y, antena.x, antena.y, proporcao)
        alcance = alcance_ate(antena, x, y, proporcao)
        if d <= alcance + 1e-9:
            resultado.append((antena, rssi(d, alcance)))
    return resultado
