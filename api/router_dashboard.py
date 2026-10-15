"""Leituras operacionais agregadas e atividade recente."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.database import get_db
from api.permissoes import Permissao, exigir_por_metodo
from api.router_equipamento import get_recency_context
from api.service_dashboard import atividade_recente, resumo

_PERMISSAO = exigir_por_metodo(
    consultar=Permissao.EQUIPAMENTOS_CONSULTAR, alterar=Permissao.EQUIPAMENTOS_ALTERAR
)
router = APIRouter(prefix="/api/dashboard", tags=["painel operacional"], dependencies=[Depends(_PERMISSAO)])


class Resumo(BaseModel):
    """Contrato de dados Resumo; valida campos e serializa a resposta da API."""
    registered: int
    disponivel: int
    atencao: int
    fora_de_servico: int
    nunca_detectado: int


class Atividade(BaseModel):
    """Contrato de dados Atividade; valida campos e serializa a resposta da API."""
    id: int
    equipamento_id: int
    equipamento_nome: str
    zona_origem: str | None
    zona_destino: str
    movimentada_em: datetime
    origem_registro: str


class Atividades(BaseModel):
    """Contrato de dados Atividades; valida campos e serializa a resposta da API."""
    items: list[Atividade]


@router.get("/resumo", response_model=Resumo)
def consultar_resumo(
    db: Session = Depends(get_db),
    recency_context: tuple[datetime, timedelta] = Depends(get_recency_context),
) -> Resumo:
    """Consulta resumo.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    return Resumo(**resumo(db, now=recency_context[0], threshold=recency_context[1]))


@router.get("/atividade", response_model=Atividades)
def consultar_atividade(
    limit: int = Query(8, ge=1, le=20),
    db: Session = Depends(get_db),
) -> Atividades:
    """Consulta atividade.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    return Atividades(items=[Atividade(**item) for item in atividade_recente(db, limit=limit)])
