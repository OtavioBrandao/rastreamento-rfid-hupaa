"""
Router HTTP do CRUD de equipamentos (ISS-008).

Responsabilidade única: validar/serializar payload e traduzir as
exceções de domínio de `api.service_equipamento` para status code.
Nenhuma regra de negócio mora aqui — mesmo padrão de
`api/router_tipos_equipamento.py`.

Mapeamento de erro:
- `EquipamentoNaoEncontrado`                 -> 404
- `EquipamentoNaoEncontradoPorIdentificador` -> 404
- `IdentificadorDuplicado`                   -> 409
- `TipoEquipamentoInvalido`                  -> 422 (tipo_id inexistente ou inativo)
- payload inválido                           -> 422, direto pelo Pydantic
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api import service_equipamento as service
from api.database import get_db
from api.schemas_equipamento import (
    EquipamentoAtualizar,
    EquipamentoCriar,
    EquipamentoPagina,
    EquipamentoResposta,
)
from api.schemas_movimentacao import MovimentacaoPagina, MovimentacaoResposta
from db.models import Equipamento
from rfid_movement import repository as movement_repository

router = APIRouter(prefix="/equipamentos", tags=["equipamentos"])


@router.get(
    "/{equipamento_id}/movimentacoes",
    response_model=MovimentacaoPagina,
    summary="Consultar histórico de movimentações",
)
def listar_movimentacoes(
    equipamento_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    inicio: datetime | None = Query(None),
    fim: datetime | None = Query(None),
    db: Session = Depends(get_db),
) -> MovimentacaoPagina:
    if any(value is not None and (value.tzinfo is None or value.utcoffset() is None)
           for value in (inicio, fim)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="inicio e fim exigem fuso horário")
    connection = db.connection()
    if not movement_repository.equipment_exists(connection, equipamento_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="equipamento inexistente")
    try:
        result = movement_repository.list_for_equipment(
            connection, equipamento_id, page=page, size=size, inicio=inicio, fim=fim
        )
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return MovimentacaoPagina(
        items=[MovimentacaoResposta(**vars(item)) for item in result.items],
        page=result.page, size=result.size, total=result.total, pages=result.pages,
    )


def _para_resposta(equipamento: Equipamento) -> EquipamentoResposta:
    """
    Monta a resposta a partir do relacionamento `tipo` já carregado pelo
    serviço (`joinedload`/`refresh` explícito) — nunca dispara query nova
    aqui. `EquipamentoResposta.model_validate` sozinho não resolveria
    `tipo_nome`, porque não é um atributo direto de `Equipamento`.
    """
    return EquipamentoResposta(
        id=equipamento.id,
        nome=equipamento.nome,
        tipo_id=equipamento.tipo_id,
        tipo_nome=equipamento.tipo.nome,
        identificador_interno=equipamento.identificador_interno,
        identificador_interno_normalizado=equipamento.identificador_interno_normalizado,
        descricao=equipamento.descricao,
        status=equipamento.status,
        created_at=equipamento.created_at,
        updated_at=equipamento.updated_at,
    )


@router.post(
    "",
    response_model=EquipamentoResposta,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastrar equipamento",
)
def criar_equipamento(
    payload: EquipamentoCriar,
    db: Session = Depends(get_db),
) -> EquipamentoResposta:
    try:
        equipamento = service.criar(
            db,
            nome=payload.nome,
            tipo_id=payload.tipo_id,
            identificador_interno=payload.identificador_interno,
            descricao=payload.descricao,
        )
    except service.TipoEquipamentoInvalido as erro:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)) from erro
    except service.IdentificadorDuplicado as erro:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(erro)) from erro
    return _para_resposta(equipamento)


@router.get(
    "",
    response_model=EquipamentoPagina,
    summary="Listar equipamentos (paginado)",
)
def listar_equipamentos(
    page: int = Query(1, ge=1),
    size: int = Query(service.TAMANHO_PAGINA_PADRAO, ge=1, le=service.TAMANHO_PAGINA_MAXIMO),
    incluir_inativos: bool = Query(False),
    db: Session = Depends(get_db),
) -> EquipamentoPagina:
    pagina = service.listar(db, page=page, size=size, incluir_inativos=incluir_inativos)
    return EquipamentoPagina(
        items=[_para_resposta(item) for item in pagina.items],
        page=pagina.page,
        size=pagina.size,
        total=pagina.total,
        pages=pagina.pages,
    )


@router.get(
    "/por-identificador/{identificador_interno}",
    response_model=EquipamentoResposta,
    summary="Buscar equipamento por identificador",
)
def buscar_equipamento_por_identificador(
    identificador_interno: str,
    db: Session = Depends(get_db),
) -> EquipamentoResposta:
    try:
        equipamento = service.buscar_por_identificador(db, identificador_interno)
    except (
        service.EquipamentoNaoEncontrado,
        service.EquipamentoNaoEncontradoPorIdentificador,
    ) as erro:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(erro)) from erro
    return _para_resposta(equipamento)


@router.get(
    "/{equipamento_id}",
    response_model=EquipamentoResposta,
    summary="Detalhar equipamento",
)
def detalhar_equipamento(
    equipamento_id: int,
    db: Session = Depends(get_db),
) -> EquipamentoResposta:
    try:
        equipamento = service.buscar_por_id(db, equipamento_id)
    except service.EquipamentoNaoEncontrado as erro:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(erro)) from erro
    return _para_resposta(equipamento)


@router.patch(
    "/{equipamento_id}",
    response_model=EquipamentoResposta,
    summary="Atualizar equipamento (parcial)",
)
def atualizar_equipamento(
    equipamento_id: int,
    payload: EquipamentoAtualizar,
    db: Session = Depends(get_db),
) -> EquipamentoResposta:
    try:
        equipamento = service.atualizar(
            db,
            equipamento_id,
            nome=payload.nome,
            tipo_id=payload.tipo_id,
            descricao=payload.descricao,
            descricao_informada="descricao" in payload.model_fields_set,
        )
    except service.EquipamentoNaoEncontrado as erro:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(erro)) from erro
    except service.TipoEquipamentoInvalido as erro:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)) from erro
    return _para_resposta(equipamento)


@router.post(
    "/{equipamento_id}/inativar",
    response_model=EquipamentoResposta,
    summary="Inativar equipamento (baixa lógica)",
)
def inativar_equipamento(
    equipamento_id: int,
    db: Session = Depends(get_db),
) -> EquipamentoResposta:
    try:
        equipamento = service.inativar(db, equipamento_id)
    except service.EquipamentoNaoEncontrado as erro:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(erro)) from erro
    return _para_resposta(equipamento)


@router.post(
    "/{equipamento_id}/reativar",
    response_model=EquipamentoResposta,
    summary="Reativar equipamento",
)
def reativar_equipamento(
    equipamento_id: int,
    db: Session = Depends(get_db),
) -> EquipamentoResposta:
    try:
        equipamento = service.reativar(db, equipamento_id)
    except service.EquipamentoNaoEncontrado as erro:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(erro)) from erro
    return _para_resposta(equipamento)
