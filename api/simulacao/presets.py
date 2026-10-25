"""Configurações iniciais dos dois cenários do simulador web (totalmente editáveis).

EASY reproduz o simulador Flet anterior: salas A e B, um portal, um leitor e
duas antenas com o mesmo alcance ilustrativo (raio 16 na escala de x, planta
880 x 560). As zonas e o portal são os mesmos cadastrados pelo launcher
(`tools/lab_launcher/seed.py`), para o mapa EASY do dashboard continuar
mostrando o resultado. Só o leitor é virtual e próprio (`sim-easy-01`).

HUPAA parte da planta de referência do 2º pavimento e das três zonas
provisórias já descritas em `frontend/src/config/mapaConfig.ts`. Os retângulos
das zonas 1–3 são aproximações dessas áreas provisórias; a circulação
vertical (escada) e TODAS as posições de leitores e antenas ficam sem
posição de propósito: elas dependem da conferência no hospital e são
ajustadas pelo operador no editor.
"""

from __future__ import annotations

import copy

ANDAR_LABORATORIO = "Laboratório RFID"
SETOR_LABORATORIO = "Bancada de testes"
PORTAL_LABORATORIO = "Portal de teste RFID"
ANDAR_SIMULACAO_HUPAA = "Simulação HUPAA"
PROPORCAO_EASY = 880 / 560
PROPORCAO_HUPAA = 2.05

_EASY = {
    "cenario": "easy",
    "proporcao": PROPORCAO_EASY,
    "destino": {"andar": ANDAR_LABORATORIO, "setor": SETOR_LABORATORIO},
    "zonas": [
        {"chave": "zona-a", "nome": "Zona A", "cor": "#2f6fb2", "referencia_planta": "sala-a",
         "area": {"x": 1, "y": 5, "largura": 49, "altura": 60}, "restrita": False},
        {"chave": "zona-b", "nome": "Zona B", "cor": "#1f8a70", "referencia_planta": "sala-b",
         "area": {"x": 50, "y": 5, "largura": 49, "altura": 60}, "restrita": False},
    ],
    "portais": [
        {"chave": "portal-easy", "nome": PORTAL_LABORATORIO, "zona_a": "zona-a",
         "zona_b": "zona-b", "posicao": {"x": 50, "y": 54}},
    ],
    "leitores": [
        {"chave": "leitor-easy", "nome": "Leitor EASY", "reader_id": "sim-easy-01",
         "modelo": "EZ700", "posicao": {"x": 50, "y": 66},
         "antenas": [
             {"chave": "antena-a", "nome": "Antena A", "porta": 1, "posicao": {"x": 28, "y": 66},
              "alcance": 16, "portal": "portal-easy", "lado": "a", "zona": "zona-a"},
             {"chave": "antena-b", "nome": "Antena B", "porta": 2, "posicao": {"x": 72, "y": 66},
              "alcance": 16, "portal": "portal-easy", "lado": "b", "zona": "zona-b"},
         ]},
    ],
}


def _leitor_hupaa(numero: int, modelo: str, antenas: list[tuple[int, str, str]]) -> dict:
    """Leitor sem posição, com antenas sem posição ligadas aos portais indicados."""
    return {
        "chave": f"leitor-{numero}", "nome": f"Leitor {numero}",
        "reader_id": f"sim-hupaa-{numero:02d}", "modelo": modelo, "posicao": None,
        "antenas": [
            {"chave": f"leitor-{numero}-antena-{porta}", "nome": f"Antena {porta}",
             "porta": porta, "posicao": None, "alcance": 6, "portal": portal, "lado": lado,
             "zona": None}
            for porta, portal, lado in antenas
        ],
    }


_HUPAA = {
    "cenario": "hupaa",
    "proporcao": PROPORCAO_HUPAA,
    "destino": None,  # definido por layout: "Simulação HUPAA" / "Layout #<id>"
    "zonas": [
        {"chave": "zona-1", "nome": "Zona 1", "cor": "#2f6fb2", "referencia_planta": None,
         "area": {"x": 13, "y": 1, "largura": 36, "altura": 28}, "restrita": False},
        {"chave": "zona-2", "nome": "Zona 2", "cor": "#1f8a70", "referencia_planta": None,
         "area": {"x": 52, "y": 1, "largura": 48, "altura": 48}, "restrita": False},
        {"chave": "zona-3", "nome": "Zona 3", "cor": "#b26b2f", "referencia_planta": None,
         "area": {"x": 12, "y": 70, "largura": 49, "altura": 30}, "restrita": False},
        {"chave": "circulacao-vertical", "nome": "Circulação vertical (escada)",
         "cor": "#7a3fb2", "referencia_planta": None, "area": None, "restrita": True},
    ],
    "portais": [
        {"chave": "portal-1-2", "nome": "Zona 1 ↔ Zona 2", "zona_a": "zona-1",
         "zona_b": "zona-2", "posicao": None},
        {"chave": "portal-2-3", "nome": "Zona 2 ↔ Zona 3", "zona_a": "zona-2",
         "zona_b": "zona-3", "posicao": None},
        {"chave": "portal-3-escada", "nome": "Zona 3 ↔ Circulação vertical", "zona_a": "zona-3",
         "zona_b": "circulacao-vertical", "posicao": None},
        {"chave": "portal-1-escada", "nome": "Zona 1 ↔ Circulação vertical", "zona_a": "zona-1",
         "zona_b": "circulacao-vertical", "posicao": None},
    ],
    "leitores": [
        _leitor_hupaa(1, "EZ700", [(1, "portal-1-2", "a"), (2, "portal-1-escada", "a")]),
        _leitor_hupaa(2, "EZ700", [(1, "portal-1-2", "b"), (2, "portal-2-3", "a")]),
        _leitor_hupaa(3, "DR_MAX", [(1, "portal-2-3", "b"), (2, "portal-3-escada", "a")]),
        _leitor_hupaa(4, "DR_MAX", [(1, "portal-3-escada", "b"), (2, "portal-1-escada", "b")]),
    ],
}

PRESETS = {"easy": _EASY, "hupaa": _HUPAA}
NOMES_PRESET = {"easy": "Laboratório EASY (padrão)", "hupaa": "Hospital HUPAA (padrão)"}


def preset(cenario: str) -> dict:
    """Cópia independente do preset do cenário."""
    return copy.deepcopy(PRESETS[cenario])


# --- teste rápido ---------------------------------------------------------------
#
# Layout pronto para iniciar sem passar pelo editor. No EASY é o próprio preset.
# No HUPAA as posições de leitores, antenas e da escada são ILUSTRATIVAS (só para
# demonstrar o fluxo), não as do hospital: o preset padrão continua sem posições.
# Antenas de um mesmo portal ficam uma em cada zona, sem alcances sobrepostos.


def _antena(leitor: int, porta: int, portal: str, lado: str, x: float, y: float) -> dict:
    """Antena posicionada, com alcance ilustrativo 5."""
    return {"chave": f"leitor-{leitor}-antena-{porta}", "nome": f"Antena {porta}", "porta": porta,
            "posicao": {"x": x, "y": y}, "alcance": 5, "portal": portal, "lado": lado,
            "zona": None}


def _hupaa_demo() -> dict:
    """HUPAA com tudo posicionado para uma demonstração imediata."""
    layout = preset("hupaa")
    escada = next(z for z in layout["zonas"] if z["chave"] == "circulacao-vertical")
    escada["area"] = {"x": 1, "y": 33, "largura": 10, "altura": 34}
    posicoes = {"portal-1-2": (51, 15), "portal-2-3": (56, 60),
                "portal-3-escada": (11, 70), "portal-1-escada": (11, 30)}
    for portal in layout["portais"]:
        x, y = posicoes[portal["chave"]]
        portal["posicao"] = {"x": x, "y": y}
    antenas = {
        1: ((30, 10), [_antena(1, 1, "portal-1-2", "a", 44, 15),
                       _antena(1, 2, "portal-1-escada", "a", 17, 22)]),
        2: ((66, 30), [_antena(2, 1, "portal-1-2", "b", 58, 15),
                       _antena(2, 2, "portal-2-3", "a", 56, 42)]),
        3: ((38, 90), [_antena(3, 1, "portal-2-3", "b", 56, 78),
                       _antena(3, 2, "portal-3-escada", "a", 17, 80)]),
        4: ((6, 50), [_antena(4, 1, "portal-3-escada", "b", 6, 62),
                      _antena(4, 2, "portal-1-escada", "b", 6, 38)]),
    }
    for leitor in layout["leitores"]:
        numero = int(leitor["chave"].rsplit("-", 1)[1])
        (x, y), lista = antenas[numero]
        leitor["posicao"] = {"x": x, "y": y}
        leitor["antenas"] = lista
    return layout


NOMES_TESTE_RAPIDO = {"easy": "Laboratório EASY (teste rápido)",
                      "hupaa": "Hospital HUPAA (teste rápido · posições ilustrativas)"}

# Equipamentos já colocados na sessão: dois cadastrados (a zona muda no
# dashboard), um com tag não cadastrada (testa o cadastro por leitura) e um sem
# etiqueta (nunca é lido). Os cadastrados usam o tipo e o identificador
# `LAB-RFID-<EPC>` do launcher, então `tools.limpeza_banco --escopo laboratorio`
# os remove.
EPC_DEMO = "E2804C41000000000000D0{:02X}"
ITENS_TESTE_RAPIDO = [
    {"nome": "Maca 01", "tipo": "Maca", "epc": EPC_DEMO.format(1), "cadastrar": True},
    {"nome": "Cadeira de rodas 01", "tipo": "Cadeira de rodas", "epc": EPC_DEMO.format(2),
     "cadastrar": True},
    {"nome": "Monitor portátil", "tipo": "Monitor multiparamétrico", "epc": EPC_DEMO.format(3),
     "cadastrar": False},
    {"nome": "Bomba de infusão", "tipo": "Bomba de infusão", "epc": None, "cadastrar": False},
]
# Fila inicial dentro da primeira zona, fora do alcance das antenas.
POSICOES_TESTE_RAPIDO = {"easy": [(10, 14), (20, 14), (30, 14), (40, 14)],
                         "hupaa": [(20, 5), (26, 5), (32, 5), (38, 5)]}


def teste_rapido(cenario: str) -> dict:
    """Layout pronto do teste rápido do cenário."""
    return preset("easy") if cenario == "easy" else _hupaa_demo()
