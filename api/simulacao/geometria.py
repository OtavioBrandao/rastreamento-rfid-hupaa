"""Detecção ilustrativa: quais antenas "enxergam" um ponto da planta.

Mesmo critério do simulador Flet anterior: distância euclidiana na escala de
x, com o eixo y corrigido pela proporção da planta, e RSSI linear entre a
antena e a borda do alcance. Não há equivalência metrológica com o hardware:
é só o gatilho que decide quando publicar uma leitura no MQTT.
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


def distancia(x1: float, y1: float, x2: float, y2: float, proporcao: float) -> float:
    """Distância na escala de x; `proporcao` = largura/altura da planta."""
    return math.hypot(x1 - x2, (y1 - y2) / proporcao)


def rssi(distancia_antena: float, alcance: float) -> int:
    """Linear de -5700 (sobre a antena) a -6700 (borda do alcance)."""
    fracao = min(max(distancia_antena / alcance, 0.0), 1.0)
    return round(RSSI_PERTO + (RSSI_LONGE - RSSI_PERTO) * fracao)


def antenas_do_layout(layout: dict) -> list[AntenaVirtual]:
    """Antenas com posição; as não posicionadas não detectam nada."""
    return [
        AntenaVirtual(antena["chave"], leitor["reader_id"], antena["porta"],
                      antena["posicao"]["x"], antena["posicao"]["y"], antena["alcance"])
        for leitor in layout.get("leitores", [])
        for antena in leitor["antenas"]
        if antena.get("posicao")
    ]


def detectar(x: float, y: float, antenas: list[AntenaVirtual], proporcao: float
             ) -> list[tuple[AntenaVirtual, int]]:
    """Antenas cujo alcance contém o ponto, com o RSSI correspondente."""
    resultado = []
    for antena in antenas:
        d = distancia(x, y, antena.x, antena.y, proporcao)
        if d <= antena.alcance:
            resultado.append((antena, rssi(d, antena.alcance)))
    return resultado
