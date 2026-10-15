"""GET /api/ativos — filtros cumulativos para dashboard e mapa."""

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.database import get_db
from api.epc import EpcInvalido, normalizar_epc
from api.permissoes import Permissao, exigir_por_metodo
from api.router_equipamento import get_recency_context
from api.schemas_busca_ativos import AtivoBusca, BuscaAtivosPagina, StatusAtivo
from api.service_busca_ativos import PAGE_SIZE_DEFAULT, PAGE_SIZE_MAX, buscar, obter

_PERMISSAO = exigir_por_metodo(
    consultar=Permissao.EQUIPAMENTOS_CONSULTAR, alterar=Permissao.EQUIPAMENTOS_ALTERAR
)
router = APIRouter(prefix="/api/ativos", tags=["consulta de ativos"], dependencies=[Depends(_PERMISSAO)])
Sort = Literal["nome", "-nome", "ultima_deteccao_em", "-ultima_deteccao_em", "prioridade"]


@router.get("", response_model=BuscaAtivosPagina, summary="Buscar ativos por filtros cumulativos")
def buscar_ativos(
    q: str | None = Query(None, min_length=1, max_length=120),
    tipo: int | None = Query(None, gt=0),
    epc: str | None = Query(None, min_length=1, max_length=32),
    status: StatusAtivo | None = Query(None),
    zona: int | None = Query(None, gt=0),
    page: int = Query(1, ge=1),
    page_size: int = Query(PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    sort: Sort = Query("nome"),
    db: Session = Depends(get_db),
    recency_context: tuple[datetime, timedelta] = Depends(get_recency_context),
) -> BuscaAtivosPagina:
    """Busca ativos.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    if q is not None:
        q = q.strip()
        if not q:
            raise HTTPException(422, detail="q não pode conter apenas espaços")
    if epc is not None:
        try:
            epc = normalizar_epc(epc)
        except EpcInvalido as error:
            raise HTTPException(422, detail=str(error)) from error
    return buscar(db, now=recency_context[0], threshold=recency_context[1], q=q,
                  tipo=tipo, epc=epc, status=status, zona=zona, page=page,
                  page_size=page_size, sort=sort)


@router.get("/{equipamento_id}", response_model=AtivoBusca, summary="Consultar um ativo pelo ID")
def obter_ativo(
    equipamento_id: int,
    db: Session = Depends(get_db),
    recency_context: tuple[datetime, timedelta] = Depends(get_recency_context),
) -> AtivoBusca:
    """Obtém ativo.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    ativo = obter(db, equipamento_id, now=recency_context[0], threshold=recency_context[1])
    if ativo is None:
        raise HTTPException(404, detail="equipamento inexistente")
    return ativo
