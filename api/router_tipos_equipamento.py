"""
Router HTTP do CRUD de tipos de equipamento (ISS-009).

Responsabilidade única: validar/serializar payload (Pydantic) e traduzir
as exceções de domínio de `api.service_tipos_equipamento` para status
code. Nenhuma regra de negócio mora aqui.

Mapeamento de erro:
- `TipoEquipamentoNaoEncontrado` -> 404
- `NomeDuplicado`               -> 409
- `TipoEquipamentoEmUso`        -> 409
- payload inválido (nome vazio) -> 422, direto pelo Pydantic
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from api import service_tipos_equipamento as service
from api.database import get_db
from api.permissoes import Permissao, exigir_por_metodo

_PERMISSAO = exigir_por_metodo(
    consultar=Permissao.EQUIPAMENTOS_CONSULTAR, alterar=Permissao.EQUIPAMENTOS_ALTERAR
)
router = APIRouter(prefix="/tipos-equipamento", tags=["tipos de equipamento"], dependencies=[Depends(_PERMISSAO)])


def _validar_nome_preenchido(valor: str | None) -> str | None:
    """
    Strip + rejeição de string vazia. Levantar ValueError aqui faz o
    FastAPI responder 422 automaticamente — é o caminho certo, em vez de
    deixar um nome só de espaços chegar no serviço e virar 500 ou, pior,
    entrar no banco.
    """
    if valor is None:
        return None
    valor = valor.strip()
    if not valor:
        raise ValueError("nome não pode ser vazio nem conter apenas espaços")
    return valor


class TipoEquipamentoCriar(BaseModel):
    nome: str = Field(..., max_length=255)
    descricao: str | None = None

    _validar_nome = field_validator("nome")(_validar_nome_preenchido)


class TipoEquipamentoAtualizar(BaseModel):
    """
    PATCH parcial. Os dois campos são opcionais, e o serviço precisa saber
    a diferença entre "descricao não veio" e "descricao veio como null" —
    por isso o router consulta `model_fields_set` em vez de olhar só o
    valor.
    """

    nome: str | None = Field(default=None, max_length=255)
    descricao: str | None = None

    _validar_nome = field_validator("nome")(_validar_nome_preenchido)


class TipoEquipamentoResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    nome_normalizado: str
    descricao: str | None
    ativo: bool
    created_at: datetime
    updated_at: datetime


class PaginaTiposEquipamento(BaseModel):
    items: list[TipoEquipamentoResposta]
    page: int
    size: int
    total: int
    pages: int


@router.post(
    "",
    response_model=TipoEquipamentoResposta,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastrar tipo de equipamento",
)
def criar_tipo(
    payload: TipoEquipamentoCriar,
    db: Session = Depends(get_db),
) -> service.TipoEquipamento:
    try:
        return service.criar(db, nome=payload.nome, descricao=payload.descricao)
    except service.NomeDuplicado as erro:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(erro)) from erro


@router.get(
    "",
    response_model=PaginaTiposEquipamento,
    summary="Listar tipos de equipamento (paginado)",
)
def listar_tipos(
    page: int = Query(1, ge=1),
    size: int = Query(service.TAMANHO_PAGINA_PADRAO, ge=1, le=service.TAMANHO_PAGINA_MAXIMO),
    incluir_inativos: bool = Query(False),
    db: Session = Depends(get_db),
) -> service.PaginaTipos:
    return service.listar(db, page=page, size=size, incluir_inativos=incluir_inativos)


@router.get(
    "/{tipo_id}",
    response_model=TipoEquipamentoResposta,
    summary="Detalhar tipo de equipamento",
)
def detalhar_tipo(
    tipo_id: int,
    db: Session = Depends(get_db),
) -> service.TipoEquipamento:
    try:
        return service.buscar_por_id(db, tipo_id)
    except service.TipoEquipamentoNaoEncontrado as erro:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(erro)) from erro


@router.patch(
    "/{tipo_id}",
    response_model=TipoEquipamentoResposta,
    summary="Atualizar tipo de equipamento (parcial)",
)
def atualizar_tipo(
    tipo_id: int,
    payload: TipoEquipamentoAtualizar,
    db: Session = Depends(get_db),
) -> service.TipoEquipamento:
    try:
        return service.atualizar(
            db,
            tipo_id,
            nome=payload.nome,
            descricao=payload.descricao,
            veio_descricao="descricao" in payload.model_fields_set,
        )
    except service.TipoEquipamentoNaoEncontrado as erro:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(erro)) from erro
    except service.NomeDuplicado as erro:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(erro)) from erro


@router.post(
    "/{tipo_id}/inativar",
    response_model=TipoEquipamentoResposta,
    summary="Inativar tipo de equipamento (baixa lógica)",
)
def inativar_tipo(
    tipo_id: int,
    db: Session = Depends(get_db),
) -> service.TipoEquipamento:
    try:
        return service.inativar(db, tipo_id)
    except service.TipoEquipamentoNaoEncontrado as erro:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(erro)) from erro
    except service.TipoEquipamentoEmUso as erro:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(erro)) from erro


@router.post(
    "/{tipo_id}/reativar",
    response_model=TipoEquipamentoResposta,
    summary="Reativar tipo de equipamento",
)
def reativar_tipo(
    tipo_id: int,
    db: Session = Depends(get_db),
) -> service.TipoEquipamento:
    try:
        return service.reativar(db, tipo_id)
    except service.TipoEquipamentoNaoEncontrado as erro:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(erro)) from erro
