"""
HTTP router for logical portal topology and antenna mappings (ISS-013).

Translates domain exceptions from `api.service_topologia_portal` to HTTP status codes:
- 404: MapeamentoNaoEncontrado, PortalNaoEncontrado, AntenaNaoEncontrada
- 409: MapeamentoAtivoExistente, MapeamentoJaEncerrado
- 422: PortalInativo, AntenaInativa, AntenaNaoPertenceAoPortal, LadoInvalido,
       FuncaoInvalida, ZonaIncompativelComLado, ZonaIncompativelComAntena
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api import service_topologia_portal as service
from api.database import get_db
from api.schemas_topologia_portal import (
    ItemTopologiaAntenaResposta,
    MapeamentoAtualizar,
    MapeamentoCriar,
    MapeamentoResposta,
    TopologiaPortalResposta,
    ZonaResumo,
)

router = APIRouter()

_NAO_ENCONTRADO = (
    service.MapeamentoNaoEncontrado,
    service.PortalNaoEncontrado,
    service.AntenaNaoEncontrada,
    service.LeitorNaoEncontrado,
)
_CONFLITO = (
    service.MapeamentoAtivoExistente,
    service.MapeamentoJaEncerrado,
)
_ENTIDADE_INVALIDA = (
    service.PortalInativo,
    service.AntenaInativa,
    service.LeitorInativo,
    service.AntenaNaoPertenceAoPortal,
    service.LadoInvalido,
    service.FuncaoInvalida,
    service.ZonaIncompativelComLado,
    service.ZonaIncompativelComAntena,
)


def _http(erro: service.ErroTopologiaPortal) -> HTTPException:
    if isinstance(erro, _NAO_ENCONTRADO):
        codigo = status.HTTP_404_NOT_FOUND
    elif isinstance(erro, _CONFLITO):
        codigo = status.HTTP_409_CONFLICT
    elif isinstance(erro, _ENTIDADE_INVALIDA):
        codigo = status.HTTP_422_UNPROCESSABLE_CONTENT
    else:  # pragma: no cover
        raise erro
    return HTTPException(codigo, detail=str(erro))


@router.post(
    "/portais/{portal_id}/mapeamentos",
    response_model=MapeamentoResposta,
    status_code=status.HTTP_201_CREATED,
    tags=["topologia-portais"],
    summary="Cadastrar mapeamento lógico de antena no portal",
)
def criar_mapeamento(
    portal_id: int, payload: MapeamentoCriar, db: Session = Depends(get_db)
) -> service.MapeamentoAntenaPortal:
    try:
        return service.criar_mapeamento(
            db,
            portal_id=portal_id,
            antena_id=payload.antena_id,
            lado=payload.lado,
            funcao=payload.funcao,
            zona_id=payload.zona_id,
        )
    except service.ErroTopologiaPortal as erro:
        raise _http(erro) from erro


@router.get(
    "/portais/{portal_id}/mapeamentos",
    response_model=list[MapeamentoResposta],
    tags=["topologia-portais"],
    summary="Listar mapeamentos do portal (ativos por padrão, histórico opcional)",
)
def listar_mapeamentos_portal(
    portal_id: int,
    incluir_historico: bool = Query(False),
    db: Session = Depends(get_db),
) -> list[service.MapeamentoAntenaPortal]:
    try:
        return service.listar_mapeamentos_portal(
            db, portal_id=portal_id, incluir_historico=incluir_historico
        )
    except service.ErroTopologiaPortal as erro:
        raise _http(erro) from erro


@router.get(
    "/portais/{portal_id}/topologia",
    response_model=TopologiaPortalResposta,
    tags=["topologia-portais"],
    summary="Consultar topologia lógica completa do portal (para motor de inferência)",
)
def obter_topologia_portal(
    portal_id: int, db: Session = Depends(get_db)
) -> TopologiaPortalResposta:
    try:
        topologia = service.obter_topologia_portal(db, portal_id)
        return TopologiaPortalResposta(
            portal_id=topologia.portal_id,
            nome=topologia.nome,
            ativo=topologia.ativo,
            zona_a=ZonaResumo(id=topologia.zona_a_id, nome=topologia.zona_a_nome),
            zona_b=ZonaResumo(id=topologia.zona_b_id, nome=topologia.zona_b_nome),
            antenas=[
                ItemTopologiaAntenaResposta(
                    mapeamento_id=item.mapeamento_id,
                    antena_id=item.antena_id,
                    reader_id=item.reader_id,
                    porta_numero=item.porta_numero,
                    lado=item.lado,
                    zona_id=item.zona_id,
                    funcao=item.funcao,
                    inicio=item.inicio,
                )
                for item in topologia.antenas
            ],
        )
    except service.ErroTopologiaPortal as erro:
        raise _http(erro) from erro


@router.get(
    "/mapeamentos-antena/{mapeamento_id}",
    response_model=MapeamentoResposta,
    tags=["topologia-portais"],
    summary="Detalhar mapeamento lógico de antena",
)
def detalhar_mapeamento(
    mapeamento_id: int, db: Session = Depends(get_db)
) -> service.MapeamentoAntenaPortal:
    try:
        return service.buscar_mapeamento_por_id(db, mapeamento_id)
    except service.ErroTopologiaPortal as erro:
        raise _http(erro) from erro


@router.patch(
    "/mapeamentos-antena/{mapeamento_id}",
    response_model=MapeamentoResposta,
    tags=["topologia-portais"],
    summary="Atualizar mapeamento lógico (temporal: encerra anterior e cria nova versão)",
)
def atualizar_mapeamento(
    mapeamento_id: int, payload: MapeamentoAtualizar, db: Session = Depends(get_db)
) -> service.MapeamentoAntenaPortal:
    try:
        return service.atualizar_mapeamento(
            db,
            mapeamento_id=mapeamento_id,
            lado=payload.lado,
            funcao=payload.funcao,
            zona_id=payload.zona_id,
        )
    except service.ErroTopologiaPortal as erro:
        raise _http(erro) from erro


@router.post(
    "/mapeamentos-antena/{mapeamento_id}/inativar",
    response_model=MapeamentoResposta,
    tags=["topologia-portais"],
    summary="Inativar mapeamento lógico (baixa temporal, preserva histórico)",
)
def inativar_mapeamento(
    mapeamento_id: int, db: Session = Depends(get_db)
) -> service.MapeamentoAntenaPortal:
    try:
        return service.inativar_mapeamento(db, mapeamento_id)
    except service.ErroTopologiaPortal as erro:
        raise _http(erro) from erro


@router.get(
    "/antenas/{antena_id}/mapeamentos",
    response_model=list[MapeamentoResposta],
    tags=["topologia-portais"],
    summary="Listar histórico cronológico de mapeamentos de uma antena",
)
def listar_historico_antena(
    antena_id: int, db: Session = Depends(get_db)
) -> list[service.MapeamentoAntenaPortal]:
    try:
        return service.listar_historico_antena(db, antena_id)
    except service.ErroTopologiaPortal as erro:
        raise _http(erro) from erro
