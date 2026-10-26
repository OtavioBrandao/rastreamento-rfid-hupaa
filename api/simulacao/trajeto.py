"""Trajetos desenhados: validação, posição no tempo simulado e amostragem.

O controle desenha o percurso com o botão pressionado e só o envia ao soltar:
pontos ``{x, y, t}`` com ``t`` em segundos desde o início do gesto. Pausas com o
botão parado viram pontos repetidos com ``t`` maior. Nada disso gera leitura;
o motor só lê a posição **executada**, interpolada linearmente entre os pontos
no relógio da simulação (sem suavização: a reta entre dois pontos amostrados
é o próprio desenho).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

MAX_PONTOS = 4000
DURACAO_MAX_S = 900.0
# Amostragem do motor: no máximo este passo de tempo simulado e de distância,
# para nenhuma antena atravessada ficar sem leitura em movimento rápido ou acelerado.
PASSO_TEMPO_S = 0.2
PASSO_DISTANCIA = 0.5
MAX_AMOSTRAS = 400


class TrajetoInvalido(ValueError):
    """Pontos fora da planta, fora de ordem ou longos demais."""


def validar(pontos: list[dict]) -> list[dict]:
    """Normaliza os pontos: coordenadas na planta, tempos crescentes a partir de 0."""
    if not 2 <= len(pontos) <= MAX_PONTOS:
        raise TrajetoInvalido(f"o trajeto precisa de 2 a {MAX_PONTOS} pontos")
    saida, anterior = [], None
    for ponto in pontos:
        try:
            x, y, t = float(ponto["x"]), float(ponto["y"]), float(ponto["t"])
        except (KeyError, TypeError, ValueError) as erro:
            raise TrajetoInvalido("cada ponto precisa de x, y e t numéricos") from erro
        if not all(math.isfinite(v) for v in (x, y, t)):
            raise TrajetoInvalido("ponto com valor inválido")
        if not (0 <= x <= 100 and 0 <= y <= 100):
            raise TrajetoInvalido("ponto fora da planta")
        if anterior is not None and t < anterior:
            raise TrajetoInvalido("os tempos do trajeto precisam ser crescentes")
        anterior = t
        saida.append({"x": round(x, 3), "y": round(y, 3), "t": round(t, 3)})
    base = saida[0]["t"]
    for ponto in saida:
        ponto["t"] = round(ponto["t"] - base, 3)
    if saida[-1]["t"] > DURACAO_MAX_S:
        raise TrajetoInvalido(f"trajeto com mais de {int(DURACAO_MAX_S // 60)} minutos")
    if saida[-1]["t"] <= 0:
        raise TrajetoInvalido("trajeto sem duração")
    return saida


def _instante(texto: str | None) -> datetime | None:
    """Lê o instante ISO guardado no trajeto (None se ausente)."""
    return datetime.fromisoformat(texto) if texto else None


def janela(item: dict) -> tuple[datetime, datetime] | None:
    """Início e fim (tempo simulado) do trajeto do item, considerando pausa."""
    trajeto = item.get("trajeto")
    if not trajeto:
        return None
    inicio = _instante(trajeto["inicio"])
    return inicio, inicio + timedelta(seconds=trajeto["pontos"][-1]["t"])


def em_execucao(item: dict, agora: datetime) -> bool:
    """O item ainda está percorrendo o trajeto (pausado conta como em execução)."""
    limites = janela(item)
    if limites is None:
        return False
    return bool(item["trajeto"].get("pausado_em")) or agora < limites[1]


def posicao(item: dict, agora: datetime) -> tuple[float, float]:
    """Posição executada no instante simulado ``agora``."""
    trajeto = item.get("trajeto")
    if not trajeto:
        return item["x"], item["y"]
    pausa = _instante(trajeto.get("pausado_em"))
    if pausa is not None:
        agora = min(agora, pausa)
    decorrido = (agora - _instante(trajeto["inicio"])).total_seconds()
    pontos = trajeto["pontos"]
    if decorrido <= 0:
        return pontos[0]["x"], pontos[0]["y"]
    if decorrido >= pontos[-1]["t"]:
        return pontos[-1]["x"], pontos[-1]["y"]
    baixo, alto = 0, len(pontos) - 1
    while alto - baixo > 1:
        meio = (baixo + alto) // 2
        if pontos[meio]["t"] <= decorrido:
            baixo = meio
        else:
            alto = meio
    a, b = pontos[baixo], pontos[alto]
    fracao = 0.0 if b["t"] == a["t"] else (decorrido - a["t"]) / (b["t"] - a["t"])
    return a["x"] + (b["x"] - a["x"]) * fracao, a["y"] + (b["y"] - a["y"]) * fracao


def amostras(item: dict, inicio: datetime, fim: datetime) -> list[tuple[datetime, float, float]]:
    """Instantes (e posições) a avaliar em ``(inicio, fim]``; parado = só ``fim``."""
    limites = janela(item)
    if (limites is None or item["trajeto"].get("pausado_em")
            or limites[1] <= inicio or limites[0] >= fim):
        x, y = posicao(item, fim)
        return [(fim, x, y)]
    duracao = (fim - inicio).total_seconds()
    # Distância percorrida pelo trecho do desenho dentro da janela.
    caminho = [posicao(item, inicio)]
    caminho += [(ponto["x"], ponto["y"]) for ponto in item["trajeto"]["pontos"]
                if inicio < limites[0] + timedelta(seconds=ponto["t"]) < fim]
    caminho.append(posicao(item, fim))
    distancia = sum(math.dist(a, b) for a, b in zip(caminho, caminho[1:]))
    passos = max(1, math.ceil(duracao / PASSO_TEMPO_S), math.ceil(distancia / PASSO_DISTANCIA))
    passos = min(passos, MAX_AMOSTRAS)
    saida = []
    for indice in range(1, passos + 1):
        instante = inicio + timedelta(seconds=duracao * indice / passos)
        x, y = posicao(item, instante)
        saida.append((instante, x, y))
    return saida
