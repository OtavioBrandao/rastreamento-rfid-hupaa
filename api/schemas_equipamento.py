"""
Schemas Pydantic do CRUD de equipamentos (ISS-008).

Separados do router (diferente do padrão usado em
`api/router_tipos_equipamento.py`, que declara os schemas inline) porque
a issue pediu explicitamente um módulo próprio — mantendo os dois
padrões coexistindo no repositório sem reescrever o que já está feito.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from rfid_location.recency import RecencyStatus


def _validar_texto_preenchido(valor: str | None) -> str | None:
    """
    Strip + rejeição de string vazia. Levantar ValueError aqui faz o
    FastAPI responder 422 automaticamente, antes de o valor chegar no
    serviço ou no banco.
    """
    if valor is None:
        return None
    valor = valor.strip()
    if not valor:
        raise ValueError("campo não pode ser vazio nem conter apenas espaços")
    return valor


class EquipamentoCriar(BaseModel):
    """Contrato de dados Equipamento Criar; valida campos e serializa a resposta da API."""
    nome: str = Field(..., max_length=255)
    tipo_id: int = Field(..., gt=0)
    identificador_interno: str = Field(..., max_length=255)
    descricao: str | None = None

    _validar_nome = field_validator("nome")(_validar_texto_preenchido)
    _validar_identificador = field_validator("identificador_interno")(
        _validar_texto_preenchido
    )


class EquipamentoAtualizar(BaseModel):
    """
    PATCH parcial. SEM `identificador_interno` de propósito: é a etiqueta
    física do ativo, imutável depois de criado — o schema nem aceita o
    campo, então tentar mandá-lo no corpo é ignorado pelo Pydantic (extra
    silenciosamente descartado), não um erro de validação.

    Mesma distinção "não veio" vs. "veio null" que `TipoEquipamentoAtualizar`
    usa para `descricao`: o router consulta `model_fields_set`.
    """

    nome: str | None = Field(default=None, max_length=255)
    tipo_id: int | None = Field(default=None, gt=0)
    descricao: str | None = None

    _validar_nome = field_validator("nome")(_validar_texto_preenchido)


class EquipamentoResposta(BaseModel):
    """Contrato de dados Equipamento Resposta; valida campos e serializa a resposta da API."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    tipo_id: int
    tipo_nome: str
    identificador_interno: str
    identificador_interno_normalizado: str
    descricao: str | None
    status: str
    ultima_zona_id: int | None
    ultima_deteccao_em: datetime | None
    estado_recencia: RecencyStatus
    # ISS-025: versão otimista; o cliente a devolve como `versao_esperada` na correção.
    versao: int
    created_at: datetime
    updated_at: datetime


class EquipamentoPagina(BaseModel):
    """Contrato de dados Equipamento Pagina; valida campos e serializa a resposta da API."""
    items: list[EquipamentoResposta]
    page: int
    size: int
    total: int
    pages: int
