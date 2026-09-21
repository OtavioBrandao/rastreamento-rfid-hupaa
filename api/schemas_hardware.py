"""
Schemas Pydantic do CRUD de leitores, antenas e portais (ISS-012).

Módulo próprio, mesmo padrão de `api/schemas_equipamento.py` e
`api/schemas_localizacao.py`; a validação de texto (strip + rejeição de
vazio/só-espaço) reaproveita o mesmo validator já usado por eles.

PATCH: os schemas `*Atualizar` não têm o campo imutável (`Antena.leitor_id`) e
o router usa `model_dump(exclude_unset=True)`, então só o que foi INFORMADO
muda. Diferente dos PATCH anteriores, um `null` EXPLÍCITO em coluna NOT NULL é
recusado com 422 (em vez de ser tratado como "não mandei"): `{"funcao": null}`
não tem significado, e ignorá-lo em silêncio esconderia o erro do cliente.
`null` continua significando "limpar" nas colunas que aceitam (`portal_id` da
antena, `endereco_rede`, `parametros_ingestao`, `localizacao_fisica`).
"""

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.schemas_equipamento import _validar_texto_preenchido
from rfid_ingestion.topics import validate_topic

# `reader_id` vira um segmento do tópico MQTT
# (easy/<env>/<site>/<portal>/<reader_id>/readings); este é o mesmo alfabeto que
# `rfid_ingestion/topics.py` aceita nos segmentos do tópico.
_ALFABETO_TOPICO = re.compile(r"^[A-Za-z0-9_-]+$")

# --- parametros_ingestao: ALLOWLIST fechada ------------------------------------------
#
# Decisão da issue: nenhuma credencial de broker no banco (senha/credencial fica
# em env/secret manager, como o DATABASE_URL). O banco não tem como reconhecer um
# segredo, então a barreira é aqui, no schema.
#
# É uma ALLOWLIST, não uma blocklist: só as chaves abaixo são aceitas, e qualquer
# outra — inclusive uma obviamente inócua como "descricao" — é rejeitada com 422.
# Uma blocklist (rejeitar "password", "token"...) deixaria passar `{"x": "hunter2"}`;
# a allowlist fecha esse caminho por construção. Além da CHAVE, o VALOR de cada
# chave tem forma validada (escalar, alfabeto restrito): nem mesmo uma chave
# permitida consegue carregar uma URL `mqtt://user:pass@host` (um tópico válido não
# tem `:` nem `@`) ou um bloco PEM.
#
# As chaves espelham o que a ingestão realmente seleciona (`rfid_ingestion/config.py`):
# o adapter por leitor (RFID_READER_ADAPTERS), o formato de timestamp do EZ700
# (EZ700_TIMESTAMP_FORMAT), o tópico e o QoS. Precisou de uma chave nova? É mudança
# de código de propósito: alguém decide, em revisão, que ela nunca carrega segredo.
# As mensagens de erro nomeiam a chave, mas NUNCA ecoam o valor recebido.
_ADAPTER = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _adapter(valor: Any) -> None:
    if not isinstance(valor, str) or not _ADAPTER.fullmatch(valor):
        raise ValueError("deve ser texto com letras, dígitos, '_' e '-' (até 64 caracteres)")


def _protocolo(valor: Any) -> None:
    if valor != "mqtt" or not isinstance(valor, str):
        raise ValueError("deve ser 'mqtt'")


def _formato_timestamp(valor: Any) -> None:
    if valor not in ("rfc3339", "epoch_ms") or not isinstance(valor, str):
        raise ValueError("deve ser 'rfc3339' ou 'epoch_ms'")


def _topico(valor: Any) -> None:
    # Mesmas regras de tópico da ingestão (fonte única). Aceita a forma de
    # assinatura (com `+`); o alfabeto dos segmentos já exclui `:`, `@` e espaço.
    if not isinstance(valor, str) or len(valor) > 255:
        raise ValueError("deve ser um tópico MQTT (texto de até 255 caracteres)")
    try:
        validate_topic(valor, subscription=True)
    except ValueError:
        raise ValueError(
            "deve seguir easy/<ambiente>/<site>/<portal>/<leitor>/readings"
        ) from None


def _qos(valor: Any) -> None:
    # `bool` é subclasse de int: `True` não é um QoS.
    if type(valor) is not int or valor not in (0, 1, 2):
        raise ValueError("deve ser o inteiro 0, 1 ou 2")


PARAMETROS_INGESTAO_PERMITIDOS: dict[str, Callable[[Any], None]] = {
    "protocolo": _protocolo,
    "adapter": _adapter,
    "formato_timestamp": _formato_timestamp,
    "topico": _topico,
    "qos": _qos,
}


def _validar_parametros_ingestao(valor: dict[str, Any] | None) -> dict[str, Any] | None:
    if valor is None:
        return None

    permitidas = sorted(PARAMETROS_INGESTAO_PERMITIDOS)
    fora = sorted(chave for chave in valor if chave not in PARAMETROS_INGESTAO_PERMITIDOS)
    if fora:
        # Nomeia as chaves (truncadas) para o cliente corrigir; não toca em valores.
        nomes = ", ".join(repr(chave)[:42] for chave in fora[:5])
        raise ValueError(
            f"parametros_ingestao só aceita as chaves {permitidas} (allowlist fechada; "
            "credenciais e qualquer outro dado ficam fora do banco, em env/secret manager). "
            f"Não permitida(s): {nomes}"
        )
    for chave, valida in PARAMETROS_INGESTAO_PERMITIDOS.items():
        if chave in valor:
            try:
                valida(valor[chave])
            except ValueError as erro:
                raise ValueError(f"parametros_ingestao.{chave} {erro}") from None
    return valor


def _validar_reader_id(valor: str | None) -> str | None:
    valor = _validar_texto_preenchido(valor)
    if valor is not None and not _ALFABETO_TOPICO.fullmatch(valor):
        raise ValueError(
            "reader_id só pode ter letras, dígitos, '_' e '-' (é um segmento do tópico MQTT)"
        )
    return valor


class _AtualizacaoParcial(BaseModel):
    """PATCH: recusa `null` explícito nas colunas NOT NULL (ver docstring do módulo)."""

    _NAO_NULOS: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _recusar_null_explicito(self):
        for campo in self.model_fields_set & self._NAO_NULOS:
            if getattr(self, campo) is None:
                raise ValueError(f"'{campo}' não pode ser null")
        return self


# --- leitores ---------------------------------------------------------------------


class LeitorCriar(BaseModel):
    reader_id: str = Field(..., max_length=64)
    fabricante: str = Field(..., max_length=255)
    modelo: str = Field(..., max_length=255)
    identificador_serial: str = Field(..., max_length=255)
    endereco_rede: str | None = Field(default=None, max_length=255)
    parametros_ingestao: dict[str, Any] | None = None

    _validar_reader_id = field_validator("reader_id")(_validar_reader_id)
    _validar_textos = field_validator("fabricante", "modelo", "identificador_serial")(
        _validar_texto_preenchido
    )
    _validar_parametros = field_validator("parametros_ingestao")(_validar_parametros_ingestao)


class LeitorAtualizar(_AtualizacaoParcial):
    """
    `status` e `ultimo_heartbeat_em` NÃO estão aqui de propósito: são
    conectividade ao vivo, geridos pela ingestão/heartbeat. Mandá-los no corpo é
    ignorado (o Pydantic descarta o campo desconhecido).
    """

    _NAO_NULOS: ClassVar[frozenset[str]] = frozenset(
        {"reader_id", "fabricante", "modelo", "identificador_serial"}
    )

    reader_id: str | None = Field(default=None, max_length=64)
    fabricante: str | None = Field(default=None, max_length=255)
    modelo: str | None = Field(default=None, max_length=255)
    identificador_serial: str | None = Field(default=None, max_length=255)
    endereco_rede: str | None = Field(default=None, max_length=255)
    parametros_ingestao: dict[str, Any] | None = None

    _validar_reader_id = field_validator("reader_id")(_validar_reader_id)
    _validar_textos = field_validator("fabricante", "modelo", "identificador_serial")(
        _validar_texto_preenchido
    )
    _validar_parametros = field_validator("parametros_ingestao")(_validar_parametros_ingestao)


class LeitorResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reader_id: str
    fabricante: str
    modelo: str
    identificador_serial: str
    endereco_rede: str | None
    parametros_ingestao: dict[str, Any] | None
    # Somente leitura: conectividade ao vivo, gerida pela ingestão/heartbeat.
    status: str
    ultimo_heartbeat_em: datetime | None
    ativo: bool
    created_at: datetime
    updated_at: datetime


class LeitorPagina(BaseModel):
    items: list[LeitorResposta]
    page: int
    size: int
    total: int
    pages: int


# --- antenas ----------------------------------------------------------------------

FuncaoAntena = Literal["entrada", "saida", "indefinido"]


class AntenaCriar(BaseModel):
    leitor_id: int = Field(..., gt=0)
    # A ingestão só aceita `antenna` inteiro >= 1 (rfid_ingestion/normalization.py).
    porta_numero: int = Field(..., gt=0)
    zona_associada_id: int = Field(..., gt=0)
    funcao: FuncaoAntena
    portal_id: int | None = Field(default=None, gt=0)


class AntenaAtualizar(_AtualizacaoParcial):
    """
    SEM `leitor_id` de propósito: a antena é fisicamente cabeada no leitor;
    trocar de leitor exigiria recriá-la. Mandá-lo no corpo é ignorado.
    `portal_id` É editável, inclusive para `null` (desassociar do portal).
    """

    _NAO_NULOS: ClassVar[frozenset[str]] = frozenset({"porta_numero", "zona_associada_id", "funcao"})

    porta_numero: int | None = Field(default=None, gt=0)
    zona_associada_id: int | None = Field(default=None, gt=0)
    funcao: FuncaoAntena | None = None
    portal_id: int | None = Field(default=None, gt=0)


class AntenaResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    leitor_id: int
    portal_id: int | None
    porta_numero: int
    zona_associada_id: int
    funcao: str
    ativo: bool
    created_at: datetime
    updated_at: datetime


class AntenaPagina(BaseModel):
    items: list[AntenaResposta]
    page: int
    size: int
    total: int
    pages: int


# --- portais ----------------------------------------------------------------------


class PortalCriar(BaseModel):
    nome: str = Field(..., max_length=255)
    zona_a_id: int = Field(..., gt=0)
    zona_b_id: int = Field(..., gt=0)
    localizacao_fisica: str | None = None

    _validar_nome = field_validator("nome")(_validar_texto_preenchido)


class PortalAtualizar(_AtualizacaoParcial):
    _NAO_NULOS: ClassVar[frozenset[str]] = frozenset({"nome", "zona_a_id", "zona_b_id"})

    nome: str | None = Field(default=None, max_length=255)
    zona_a_id: int | None = Field(default=None, gt=0)
    zona_b_id: int | None = Field(default=None, gt=0)
    localizacao_fisica: str | None = None

    _validar_nome = field_validator("nome")(_validar_texto_preenchido)


class PortalResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    zona_a_id: int
    zona_b_id: int
    localizacao_fisica: str | None
    ativo: bool
    created_at: datetime
    updated_at: datetime


class PortalPagina(BaseModel):
    items: list[PortalResposta]
    page: int
    size: int
    total: int
    pages: int
