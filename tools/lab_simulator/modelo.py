"""Regras do simulador visual, sem dependência de interface.

Coordenadas em 0–100, as mesmas de ``frontend/src/config/mapaConfig.ts`` para o
laboratório EASY: antena A em (28, 66), antena B em (72, 66), leitor em
(50, 66) e portal em (50, 54).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from api.epc import normalizar_epc


@dataclass(frozen=True)
class Antena:
    porta: int
    nome: str
    x: float
    y: float


ANTENAS = (Antena(1, "Antena A", 28, 66), Antena(2, "Antena B", 72, 66))
LEITOR = (50, 66)
PORTAL = (50, 54)
# A planta é desenhada mais larga que alta; uma unidade em y vale PROPORCAO_Y
# unidades em x. Sem isso o alcance seria uma elipse, não o círculo desenhado.
PROPORCAO_Y = 560 / 880
# Alcance ilustrativo, sem calibração física; os círculos não se sobrepõem,
# então a reflexão (origem ainda lendo após a passagem) não ocorre por padrão.
RAIO = 16.0
RSSI_PERTO = -5700
RSSI_LONGE = -6700
# Intervalo entre leituras da mesma tag na mesma antena enquanto estiver no alcance.
PERIODO_LEITURA_S = 0.2
MARGEM = 4.0
DISTANCIA_MINIMA = 8.0
MAX_ITENS = 12
PREFIXO_EPC = "E2804C41"


@dataclass
class Item:
    nome: str
    epc: str
    x: float
    y: float
    ultima_leitura: dict[int, float] = field(default_factory=dict)


def rssi(distancia: float) -> int:
    """Linear de -5700 (sobre a antena) a -6700 (borda do alcance)."""
    fracao = min(max(distancia / RAIO, 0.0), 1.0)
    return round(RSSI_PERTO + (RSSI_LONGE - RSSI_PERTO) * fracao)


def distancia(x1: float, y1: float, x2: float, y2: float) -> float:
    """Distância na escala de x, corrigindo a proporção da planta."""
    return math.hypot(x1 - x2, (y1 - y2) * PROPORCAO_Y)


def detectar(x: float, y: float) -> list[tuple[Antena, int]]:
    """Antenas cujo alcance contém o ponto, com o RSSI correspondente."""
    resultado = []
    for antena in ANTENAS:
        distancia_antena = distancia(x, y, antena.x, antena.y)
        if distancia_antena <= RAIO:
            resultado.append((antena, rssi(distancia_antena)))
    return resultado


def limitar(x: float, y: float) -> tuple[float, float]:
    return (min(max(x, MARGEM), 100 - MARGEM), min(max(y, MARGEM), 100 - MARGEM))


def gerar_epcs(quantidade: int, rng: random.Random, existentes: set[str] = frozenset()
               ) -> list[str]:
    """EPCs de 96 bits aleatórios com prefixo de laboratório, sem repetição."""
    if not 1 <= quantidade <= MAX_ITENS:
        raise ValueError(f"escolha de 1 a {MAX_ITENS} itens")
    epcs: list[str] = []
    while len(epcs) < quantidade:
        epc = normalizar_epc(PREFIXO_EPC + f"{rng.getrandbits(64):016X}")
        if epc not in existentes and epc not in epcs:
            epcs.append(epc)
    return epcs


def posicoes_iniciais(quantidade: int, rng: random.Random) -> list[tuple[float, float]]:
    """Posições aleatórias fora do alcance das antenas e afastadas entre si."""
    posicoes: list[tuple[float, float]] = []
    tentativas = 0
    while len(posicoes) < quantidade:
        tentativas += 1
        if tentativas > 10_000:
            raise RuntimeError("não foi possível posicionar os itens sem sobreposição")
        x = rng.uniform(MARGEM + 2, 100 - MARGEM - 2)
        y = rng.uniform(MARGEM + 6, 100 - MARGEM - 2)
        if detectar(x, y):
            continue
        if any(distancia(x, y, px, py) < DISTANCIA_MINIMA for px, py in posicoes):
            continue
        posicoes.append((x, y))
    return posicoes


def criar_itens(nomes: list[str], rng: random.Random) -> list[Item]:
    nomes = [nome.strip() for nome in nomes]
    if any(not nome for nome in nomes):
        raise ValueError("informe um nome para cada item")
    if len({nome.casefold() for nome in nomes}) != len(nomes):
        raise ValueError("os nomes dos itens devem ser diferentes")
    epcs = gerar_epcs(len(nomes), rng)
    return [Item(nome, epc, x, y) for nome, epc, (x, y)
            in zip(nomes, epcs, posicoes_iniciais(len(nomes), rng), strict=True)]


def leituras_devidas(itens: list[Item], agora: float) -> list[tuple[Item, Antena, int]]:
    """Leituras a emitir neste instante, no máximo uma por item e antena por período."""
    devidas = []
    for item in itens:
        for antena, valor in detectar(item.x, item.y):
            anterior = item.ultima_leitura.get(antena.porta)
            # Tolerância: o ciclo da interface (0,1 s) não cai exatamente no período.
            if anterior is None or agora - anterior >= PERIODO_LEITURA_S - 0.01:
                item.ultima_leitura[antena.porta] = agora
                devidas.append((item, antena, valor))
    return devidas
