"""
Schemas Pydantic do CRUD da hierarquia física andar -> setor -> zona (ISS-011).

Módulo próprio, mesmo padrão de `api/schemas_equipamento.py`. A validação de
`nome` (strip + rejeição de string vazia/só-espaço) reaproveita o MESMO
validator já usado por equipamentos, em vez de reinventar um novo.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.schemas_equipamento import _validar_texto_preenchido


class _CamposEditaveis(BaseModel):
    """
    Campos comuns de criação. `descricao` e `referencia_planta` são
    opcionais e sem validação de conteúdo: string vazia é um valor legítimo
    ("sem referência"), diferente do `nome`, que precisa existir.
    """

    nome: str = Field(..., max_length=255)
    descricao: str | None = None
    referencia_planta: str | None = Field(default=None, max_length=255)

    _validar_nome = field_validator("nome")(_validar_texto_preenchido)


class _CamposAtualizaveis(BaseModel):
    """
    PATCH parcial. O router consulta `model_fields_set` para separar "não
    mandei o campo" de "mandei null para limpar" em `descricao` e
    `referencia_planta`. SEM o id do pai de propósito: a hierarquia é
    imutável depois de criada, então o schema nem aceita o campo (ele é
    descartado silenciosamente pelo Pydantic, como `identificador_interno`
    em `EquipamentoAtualizar`).
    """

    nome: str | None = Field(default=None, max_length=255)
    descricao: str | None = None
    referencia_planta: str | None = Field(default=None, max_length=255)

    _validar_nome = field_validator("nome")(_validar_texto_preenchido)


class _RespostaBase(BaseModel):
    """Contrato de dados _Resposta Base; valida campos e serializa a resposta da API."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    nome_normalizado: str
    descricao: str | None
    referencia_planta: str | None
    ativo: bool


# --- andares ---------------------------------------------------------------------


class AndarCriar(_CamposEditaveis):
    """Contrato de dados Andar Criar; valida campos e serializa a resposta da API."""
    pass


class AndarAtualizar(_CamposAtualizaveis):
    """Contrato de dados Andar Atualizar; valida campos e serializa a resposta da API."""
    pass


class AndarResposta(_RespostaBase):
    """Contrato de dados Andar Resposta; valida campos e serializa a resposta da API."""
    created_at: datetime
    updated_at: datetime


class AndarPagina(BaseModel):
    """Contrato de dados Andar Pagina; valida campos e serializa a resposta da API."""
    items: list[AndarResposta]
    page: int
    size: int
    total: int
    pages: int


# --- setores ---------------------------------------------------------------------


class SetorCriar(_CamposEditaveis):
    """Contrato de dados Setor Criar; valida campos e serializa a resposta da API."""
    andar_id: int = Field(..., gt=0)


class SetorAtualizar(_CamposAtualizaveis):
    """Contrato de dados Setor Atualizar; valida campos e serializa a resposta da API."""
    pass


class SetorResposta(_RespostaBase):
    """Contrato de dados Setor Resposta; valida campos e serializa a resposta da API."""
    andar_id: int
    created_at: datetime
    updated_at: datetime


class SetorPagina(BaseModel):
    """Contrato de dados Setor Pagina; valida campos e serializa a resposta da API."""
    items: list[SetorResposta]
    page: int
    size: int
    total: int
    pages: int


# --- zonas -----------------------------------------------------------------------


class ZonaCriar(_CamposEditaveis):
    """Contrato de dados Zona Criar; valida campos e serializa a resposta da API."""
    setor_id: int = Field(..., gt=0)
    # Anotação de "zona morta" (só a zona tem). Opcional, como `descricao`.
    observacoes: str | None = None


class ZonaAtualizar(_CamposAtualizaveis):
    # O router consulta `model_fields_set` para separar "não mandei" de
    # "mandei null para limpar", igual a `descricao`/`referencia_planta`.
    """Contrato de dados Zona Atualizar; valida campos e serializa a resposta da API."""
    observacoes: str | None = None


class ZonaResposta(_RespostaBase):
    """Contrato de dados Zona Resposta; valida campos e serializa a resposta da API."""
    setor_id: int
    observacoes: str | None
    created_at: datetime
    updated_at: datetime


class ZonaPagina(BaseModel):
    """Contrato de dados Zona Pagina; valida campos e serializa a resposta da API."""
    items: list[ZonaResposta]
    page: int
    size: int
    total: int
    pages: int


# --- árvore ----------------------------------------------------------------------


class ZonaArvore(_RespostaBase):
    """Contrato de dados Zona Arvore; valida campos e serializa a resposta da API."""
    setor_id: int
    observacoes: str | None


class SetorArvore(_RespostaBase):
    """Contrato de dados Setor Arvore; valida campos e serializa a resposta da API."""
    andar_id: int
    zonas: list[ZonaArvore]


class AndarArvore(_RespostaBase):
    """Contrato de dados Andar Arvore; valida campos e serializa a resposta da API."""
    setores: list[SetorArvore]
