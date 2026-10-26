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

from .esquema import ALCANCE_PADRAO, FATOR_TRASEIRO_PADRAO

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
         # Antenas na parede de baixo, com a visada (270° = cima) para dentro de cada sala.
         "antenas": [
             {"chave": "antena-a", "nome": "Antena A", "porta": 1, "posicao": {"x": 28, "y": 66},
              "alcance": 11, "orientacao": 270, "fator_traseiro": 0.35,
              "portal": "portal-easy", "lado": "a", "zona": "zona-a"},
             {"chave": "antena-b", "nome": "Antena B", "porta": 2, "posicao": {"x": 72, "y": 66},
              "alcance": 11, "orientacao": 270, "fator_traseiro": 0.35,
              "portal": "portal-easy", "lado": "b", "zona": "zona-b"},
         ]},
    ],
}


def _leitor_hupaa(numero: int, modelo: str, antenas: list[tuple[int, str | None, str | None, str | None]],
                  nome: str | None = None, alerta: bool = False) -> dict:
    """Leitor sem posição; antenas (porta, portal, lado, zona) sem posição, visada à direita."""
    return {
        "chave": f"leitor-{numero}", "nome": nome or f"Leitor {numero}",
        "reader_id": f"sim-hupaa-{numero:02d}", "modelo": modelo, "posicao": None,
        "alerta_area_restrita": alerta,
        "antenas": [
            {"chave": f"leitor-{numero}-antena-{porta}", "nome": f"Antena {porta}",
             "porta": porta, "posicao": None, "alcance": ALCANCE_PADRAO, "orientacao": 0,
             "fator_traseiro": FATOR_TRASEIRO_PADRAO, "portal": portal, "lado": lado,
             "zona": zona}
            for porta, portal, lado, zona in antenas
        ],
    }


# Leitor 5: DR Max de área restrita. Uma antena basta (dentro da zona monitorada,
# sem portal): cada leitura processada vira alerta. A escada fica sem área de
# propósito: quem sabe qual circulação vertical é a escada posiciona.
NOME_LEITOR_RESTRITO = "Leitor 5 · área restrita"

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
        {"chave": "circulacao-vertical", "nome": "Escada (área restrita)",
         "cor": "#c2413b", "referencia_planta": None, "area": None, "restrita": True},
    ],
    "portais": [
        {"chave": "portal-1-2", "nome": "Portal para a Zona 2", "zona_a": "zona-1",
         "zona_b": "zona-2", "posicao": None},
        {"chave": "portal-2-3", "nome": "Portal para a Zona 3", "zona_a": "zona-2",
         "zona_b": "zona-3", "posicao": None},
    ],
    "leitores": [
        _leitor_hupaa(1, "EZ700", [(1, "portal-1-2", "a", None)]),
        _leitor_hupaa(2, "EZ700", [(1, "portal-1-2", "b", None)]),
        _leitor_hupaa(3, "DR_MAX", [(1, "portal-2-3", "a", None)]),
        _leitor_hupaa(4, "DR_MAX", [(1, "portal-2-3", "b", None)]),
        _leitor_hupaa(5, "DR_MAX", [(1, None, None, "circulacao-vertical")],
                      NOME_LEITOR_RESTRITO, alerta=True),
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


def _posicionar(layout: dict, numero: int, leitor: tuple[float, float],
                antena: tuple[float, float], orientacao: float) -> None:
    """Posição ilustrativa do leitor e da antena 1, com a visada informada."""
    alvo = next(item for item in layout["leitores"] if item["chave"] == f"leitor-{numero}")
    alvo["posicao"] = dict(zip("xy", leitor))
    alvo["antenas"][0].update(posicao=dict(zip("xy", antena)), orientacao=orientacao)


def _hupaa_demo() -> dict:
    """HUPAA com tudo posicionado para uma demonstração imediata.

    Cada antena olha para dentro da própria zona (visada direta), de costas para o
    portal: a tag é lida de um lado e depois do outro, e os alcances não se tocam.
    """
    layout = preset("hupaa")
    escada = next(z for z in layout["zonas"] if z["chave"] == "circulacao-vertical")
    escada["area"] = {"x": 1, "y": 33, "largura": 10, "altura": 34}
    for portal, (x, y) in {"portal-1-2": (51, 15), "portal-2-3": (56, 60)}.items():
        next(p for p in layout["portais"] if p["chave"] == portal)["posicao"] = {"x": x, "y": y}
    _posicionar(layout, 1, (45, 25), (45, 15), 180)   # Zona 1, olhando para a esquerda
    _posicionar(layout, 2, (57, 25), (57, 15), 0)     # Zona 2, olhando para a direita
    _posicionar(layout, 3, (64, 44), (56, 44), 270)   # Zona 2, olhando para cima
    _posicionar(layout, 4, (64, 76), (56, 76), 90)    # Zona 3, olhando para baixo
    _posicionar(layout, 5, (6, 36), (6, 40), 90)      # escada, olhando para baixo
    return layout


def _ids_proprios(layout: dict) -> dict:
    """Leitores `sim-demo-*`: o teste rápido nunca disputa leitor com os layouts do usuário."""
    for leitor in layout["leitores"]:
        leitor["reader_id"] = leitor["reader_id"].replace("sim-", "sim-demo-", 1)
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
# Coluna inicial dentro da primeira zona, fora do alcance das antenas, sem nomes sobrepostos.
POSICOES_TESTE_RAPIDO = {"easy": [(12, 12), (12, 22), (12, 32), (12, 42)],
                         "hupaa": [(19, 6), (19, 13), (19, 20), (19, 27)]}


def teste_rapido(cenario: str) -> dict:
    """Layout pronto do teste rápido do cenário."""
    return _ids_proprios(preset("easy") if cenario == "easy" else _hupaa_demo())
