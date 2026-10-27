"""Contrato do layout do simulador web e as regras que o tornam aplicável.

Coordenadas normalizadas 0–100 nos dois eixos, relativas à planta de cada
cenário: o desenho pode mudar de tamanho na tela sem perder o posicionamento.
`proporcao` (largura/altura da planta) corrige a escala vertical na distância,
para o alcance ilustrativo ser um círculo na tela, não uma elipse.

As regras espelham a topologia do MVP (ADR 0006/0008): um portal liga duas
zonas distintas; uma antena pertence a UM leitor e, opcionalmente, a um
portal, com lado lógico A/B cuja zona é a zona daquele lado do portal; um
portal pode reunir antenas de leitores diferentes. Elementos sem posição são
aceitos (ainda não posicionados na planta) e simplesmente não detectam nada.
"""

from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.normalizacao import normalizar_nome

from .geometria import alcance_na_direcao

MAX_ANTENAS_POR_LEITOR = 4
MAX_LEITORES = 24
MAX_ZONAS = 40
MAX_PORTAIS = 40
CHAVE = r"^[a-z0-9][a-z0-9-]{0,39}$"
READER_ID = re.compile(r"^sim-[a-z0-9][a-z0-9-]{0,40}$")

# Padrões das antenas novas (menores que os 6–16 anteriores, para não poluir a planta).
ALCANCE_PADRAO = 4.0
FATOR_TRASEIRO_PADRAO = 0.35

MODELOS_LEITOR: dict[str, dict] = {
    "EZ700": {"nome": "Identix EZ700", "max_antenas": 4,
              "observacao": "Payload MQTT observado nos ensaios físicos do EASY."},
    "DR_MAX": {"nome": "Identix DR Max", "max_antenas": 4,
               "observacao": "Somente virtual: integração física ao MQTT ainda não validada; "
                             "o simulador publica no mesmo contrato canônico usado pelo EZ700."},
}


class Ponto(BaseModel):
    """Posição normalizada na planta."""

    model_config = ConfigDict(extra="forbid")
    x: float = Field(..., ge=0, le=100)
    y: float = Field(..., ge=0, le=100)


class Area(BaseModel):
    """Retângulo de delimitação de zona, em coordenadas normalizadas."""

    model_config = ConfigDict(extra="forbid")
    x: float = Field(..., ge=0, le=100)
    y: float = Field(..., ge=0, le=100)
    largura: float = Field(..., gt=0, le=100)
    altura: float = Field(..., gt=0, le=100)

    @model_validator(mode="after")
    def dentro_da_planta(self) -> Area:
        """A área inteira cabe na planta (tolerância de arredondamento)."""
        if self.x + self.largura > 100.01 or self.y + self.altura > 100.01:
            raise ValueError("a delimitação ultrapassa os limites da planta")
        return self


class ZonaLayout(BaseModel):
    """Zona lógica da planta; `area` nula = ainda não delimitada."""

    model_config = ConfigDict(extra="forbid")
    chave: str = Field(..., pattern=CHAVE)
    nome: str = Field(..., min_length=1, max_length=80)
    cor: str = Field("#2f6fb2", pattern=r"^#[0-9a-fA-F]{6}$")
    area: Area | None = None
    referencia_planta: str | None = Field(None, max_length=60)
    restrita: bool = False
    # Onde o nome da zona aparece no mapa do HU (arrastável); nulo = canto da área.
    rotulo: Ponto | None = None

    @field_validator("nome")
    @classmethod
    def nome_preenchido(cls, valor: str) -> str:
        """Nome sem espaços nas pontas e não vazio."""
        valor = valor.strip()
        if not valor:
            raise ValueError("nome da zona não pode ficar vazio")
        return valor


class PortalLayout(BaseModel):
    """Conexão entre duas zonas, detectada pelas antenas associadas a ele."""

    model_config = ConfigDict(extra="forbid")
    chave: str = Field(..., pattern=CHAVE)
    nome: str = Field(..., min_length=1, max_length=120)
    zona_a: str
    zona_b: str
    posicao: Ponto | None = None
    # 'entrada': portal da zona B = um leitor com pelo menos duas antenas na entrada
    # dela, lado A = "fora" (circulação): 1 → 2 entra na zona B, 2 → 1 sai para fora.
    modo: Literal["direcional", "entrada"] = "direcional"


class AntenaLayout(BaseModel):
    """Porta física de um leitor virtual e sua área de detecção ilustrativa."""

    model_config = ConfigDict(extra="forbid")
    chave: str = Field(..., pattern=CHAVE)
    nome: str = Field(..., min_length=1, max_length=60)
    porta: int = Field(..., ge=1, le=MAX_ANTENAS_POR_LEITOR)
    posicao: Ponto | None = None
    alcance: float = Field(ALCANCE_PADRAO, ge=1, le=40)
    # Visada direta em graus da tela (0 direita, 90 baixo, 180 esquerda, 270 cima).
    # Nula = omnidirecional (layouts salvos antes da antena direcional).
    orientacao: float | None = Field(None, ge=0, le=360)
    fator_traseiro: float = Field(FATOR_TRASEIRO_PADRAO, ge=0.1, le=1)

    @field_validator("orientacao")
    @classmethod
    def angulo_normalizado(cls, valor: float | None) -> float | None:
        """360° é a mesma visada de 0°."""
        return None if valor is None else round(valor % 360, 1)
    portal: str | None = None
    lado: Literal["a", "b"] | None = None
    zona: str | None = None


class LeitorLayout(BaseModel):
    """Leitor virtual: modelo, identificador lógico do MQTT e de 1 a 4 antenas."""

    model_config = ConfigDict(extra="forbid")
    chave: str = Field(..., pattern=CHAVE)
    nome: str = Field(..., min_length=1, max_length=60)
    reader_id: str = Field(..., max_length=45)
    modelo: Literal["EZ700", "DR_MAX"]
    posicao: Ponto | None = None
    antenas: list[AntenaLayout]
    # Leitor de área restrita: basta UMA antena dentro da zona monitorada (sem portal);
    # cada leitura processada pelo sistema vira alerta. Não confirma passagem nem direção.
    alerta_area_restrita: bool = False

    @field_validator("antenas")
    @classmethod
    def uma_a_quatro_antenas(cls, valor: list[AntenaLayout]) -> list[AntenaLayout]:
        """O limite vale para cada leitor; mais leitores podem ser adicionados."""
        if not 1 <= len(valor) <= MAX_ANTENAS_POR_LEITOR:
            raise ValueError(f"cada leitor aceita de 1 a {MAX_ANTENAS_POR_LEITOR} antenas")
        return valor

    @field_validator("reader_id")
    @classmethod
    def reader_id_simulado(cls, valor: str) -> str:
        """Leitores virtuais sempre com prefixo `sim-`: nunca colidem com um físico."""
        valor = valor.strip().lower()
        if not READER_ID.fullmatch(valor):
            raise ValueError("identificador lógico deve começar com 'sim-' e usar a-z, 0-9 e '-'")
        return valor


class Destino(BaseModel):
    """Andar e setor onde as zonas do layout são cadastradas ao iniciar a simulação."""

    model_config = ConfigDict(extra="forbid")
    andar: str = Field(..., min_length=1, max_length=80)
    setor: str = Field(..., min_length=1, max_length=80)


class Layout(BaseModel):
    """Configuração completa da planta de simulação."""

    model_config = ConfigDict(extra="forbid")
    cenario: Literal["easy", "hupaa"]
    proporcao: float = Field(..., gt=0.3, le=4)
    destino: Destino | None = None
    zonas: list[ZonaLayout] = Field(default_factory=list, max_length=MAX_ZONAS)
    portais: list[PortalLayout] = Field(default_factory=list, max_length=MAX_PORTAIS)
    leitores: list[LeitorLayout] = Field(default_factory=list, max_length=MAX_LEITORES)

    @model_validator(mode="after")
    def coerente(self) -> Layout:
        """Recusa associações impossíveis; deriva a zona da antena pelo lado do portal."""
        erros: list[str] = []
        _unicos(erros, "zona", [zona.chave for zona in self.zonas])
        _unicos(erros, "nome de zona", [normalizar_nome(zona.nome) for zona in self.zonas])
        _unicos(erros, "portal", [portal.chave for portal in self.portais])
        _unicos(erros, "leitor", [leitor.chave for leitor in self.leitores])
        _unicos(erros, "identificador lógico", [leitor.reader_id for leitor in self.leitores])
        _unicos(erros, "antena", [antena.chave for leitor in self.leitores
                                  for antena in leitor.antenas])
        zonas = {zona.chave for zona in self.zonas}
        portais = {portal.chave: portal for portal in self.portais}
        for portal in self.portais:
            if portal.zona_a not in zonas or portal.zona_b not in zonas:
                erros.append(f"portal '{portal.nome}' liga zona inexistente")
            elif portal.zona_a == portal.zona_b:
                erros.append(f"portal '{portal.nome}' precisa ligar duas zonas diferentes")
        for leitor in self.leitores:
            _unicos(erros, f"porta do leitor '{leitor.nome}'",
                    [antena.porta for antena in leitor.antenas])
            for antena in leitor.antenas:
                rotulo = f"{leitor.nome} / {antena.nome}"
                if antena.portal is None:
                    if antena.lado is not None:
                        erros.append(f"{rotulo}: lado A/B exige um portal")
                    if antena.zona is None:
                        erros.append(f"{rotulo}: escolha um portal ou uma zona")
                    elif antena.zona not in zonas:
                        erros.append(f"{rotulo}: zona inexistente")
                    continue
                portal = portais.get(antena.portal)
                if portal is None:
                    erros.append(f"{rotulo}: portal inexistente")
                    continue
                if antena.lado is None:
                    erros.append(f"{rotulo}: informe o lado lógico A ou B do portal")
                    continue
                esperada = portal.zona_a if antena.lado == "a" else portal.zona_b
                if antena.zona is not None and antena.zona != esperada:
                    erros.append(f"{rotulo}: a zona do lado {antena.lado.upper()} do portal "
                                 f"'{portal.nome}' é outra")
                antena.zona = esperada
        if erros:
            raise ValueError("; ".join(erros))
        return self


def _unicos(erros: list[str], rotulo: str, valores: list) -> None:
    """Acrescenta um erro por valor repetido."""
    vistos: set = set()
    for valor in valores:
        if valor in vistos:
            erros.append(f"{rotulo} repetido: {valor}")
        vistos.add(valor)


def _alcance_entre(antena: AntenaLayout, alvo: AntenaLayout, proporcao: float) -> float:
    """Alcance efetivo da antena na direção da outra (considera a visada)."""
    angulo = math.atan2((alvo.posicao.y - antena.posicao.y) / proporcao,
                        alvo.posicao.x - antena.posicao.x)
    return alcance_na_direcao(antena.alcance, antena.orientacao, antena.fator_traseiro, angulo)


def ponto_unico(antena: AntenaLayout, outra: AntenaLayout) -> bool:
    """Duas antenas no mesmo ponto valem como UM ponto de detecção (ex.: leitor da zona
    restrita): mesmo lado e mesma zona, cada uma num portal. A inferência trata cada
    portal à parte, então cada entrada confirma a própria passagem."""
    return (antena.portal is not None and outra.portal is not None
            and antena.portal != outra.portal and antena.lado == outra.lado
            and antena.zona == outra.zona)


def avisos(layout: Layout) -> list[str]:
    """Situações aceitas, mas que impedem parte da demonstração (não bloqueiam salvar)."""
    resultado = []
    lados: dict[str, set[str]] = {portal.chave: set() for portal in layout.portais}
    for leitor in layout.leitores:
        if leitor.posicao is None:
            resultado.append(f"{leitor.nome} ainda não foi posicionado na planta")
        for antena in leitor.antenas:
            if antena.posicao is None:
                resultado.append(f"{leitor.nome} / {antena.nome} sem posição: não detecta tags")
            if antena.portal and antena.lado:
                lados[antena.portal].add(antena.lado)
    nomes_zonas = {zona.chave: zona.nome for zona in layout.zonas}
    # A zona restrita vigiada por um portal de zona restrita não precisa de antena de portal.
    vigiadas = {antena.zona for leitor in layout.leitores if leitor.alerta_area_restrita
                for antena in leitor.antenas}
    for portal in layout.portais:
        for lado, zona in (("a", portal.zona_a), ("b", portal.zona_b)):
            if lado not in lados[portal.chave] and zona not in vigiadas:
                resultado.append(
                    f"portal '{portal.nome}': nenhuma antena no lado {lado.upper()} "
                    f"({nomes_zonas.get(zona, zona)}), então a passagem por ele nunca é "
                    "confirmada; ligue uma antena a esse lado ou remova o portal se essa "
                    "entrada é vigiada só pelo portal de zona restrita")
    # O lado "fora" de um portal de entrada (ex.: circulação) não precisa de área.
    fora = {portal.zona_a for portal in layout.portais if portal.modo == "entrada"}
    for zona in layout.zonas:
        if zona.area is None and zona.chave not in fora:
            resultado.append(f"zona '{zona.nome}' ainda não foi delimitada na planta")
    for portal in layout.portais:
        if portal.modo == "entrada" and not any(
                {a.lado for a in leitor.antenas if a.portal == portal.chave} == {"a", "b"}
                for leitor in layout.leitores):
            resultado.append(f"portal '{portal.nome}': portal de entrada precisa de um leitor com "
                             "as duas antenas, uma de cada lado")
    restritas = {zona.chave for zona in layout.zonas if zona.restrita}
    for leitor in layout.leitores:
        if leitor.alerta_area_restrita and not any(a.zona in restritas for a in leitor.antenas):
            resultado.append(f"{leitor.nome} é portal de zona restrita, mas nenhuma antena dele "
                             "está numa zona marcada como restrita")
    posicionadas = [(leitor, antena) for leitor in layout.leitores for antena in leitor.antenas
                    if antena.posicao is not None]
    for i, (leitor, antena) in enumerate(posicionadas):
        for outro_leitor, outra in posicionadas[i + 1:]:
            d = math.hypot(antena.posicao.x - outra.posicao.x,
                           (antena.posicao.y - outra.posicao.y) / layout.proporcao)
            nomes = f"{leitor.nome} / {antena.nome} e {outro_leitor.nome} / {outra.nome}"
            if d < 1 and not ponto_unico(antena, outra):
                resultado.append(f"{nomes} estão no mesmo ponto; só faz sentido se forem o "
                                 "mesmo lado de portais diferentes, na mesma zona")
            elif (antena.portal and antena.portal == outra.portal and antena.lado != outra.lado
                  and d <= _alcance_entre(antena, outra, layout.proporcao)
                  + _alcance_entre(outra, antena, layout.proporcao)):
                resultado.append(f"{nomes}: alcances dos lados A e B se sobrepõem, então a "
                                 "direção da passagem não é confirmada; afaste-as ou reduza o alcance")
    return resultado
