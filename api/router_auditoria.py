"""
Consulta da trilha de auditoria (ISS-028). Só leitura: a trilha é
append-only no banco e não há rota de escrita. Exige `auditoria:consultar`
(só administrador).

Filtros combinam por AND. `desde` é inclusivo e `ate` exclusivo; os dois
exigem fuso horário. Ordem: mais recente primeiro (`registrado_em`, `id`).
"""

import math
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.database import get_db
from api.permissoes import Permissao, exigir
from api.timestamps import em_utc
from db.models import ACOES_AUDITORIA, ORIGENS_AUDITORIA, Auditoria, Usuario

router = APIRouter(
    prefix="/auditorias", tags=["auditoria"],
    dependencies=[Depends(exigir(Permissao.AUDITORIA_CONSULTAR))],
)

AcaoAuditoria = Literal[ACOES_AUDITORIA]  # type: ignore[valid-type]
OrigemAuditoria = Literal[ORIGENS_AUDITORIA]  # type: ignore[valid-type]


class AuditoriaResposta(BaseModel):
    """Contrato de dados Auditoria Resposta; valida campos e serializa a resposta da API."""
    id: int
    registrado_em: datetime
    acao: str
    origem: str
    entidade: str
    entidade_id: int | None
    usuario_id: int | None
    usuario_nome: str | None
    motivo: str | None
    correlation_id: str | None
    dados_antes: dict[str, Any] | None
    dados_depois: dict[str, Any] | None


class AuditoriaPagina(BaseModel):
    """Contrato de dados Auditoria Pagina; valida campos e serializa a resposta da API."""
    items: list[AuditoriaResposta]
    page: int
    size: int
    total: int
    pages: int


def _consulta_base():
    """Cria consulta de auditoria com os filtros e vínculos usados pela listagem."""
    return (
        select(Auditoria, Usuario.nome)
        .outerjoin(Usuario, Usuario.id == Auditoria.usuario_id)
    )


def _resposta(linha: Auditoria, usuario_nome: str | None) -> AuditoriaResposta:
    """Converte registro persistido de auditoria em resposta pública."""
    return AuditoriaResposta(
        id=linha.id, registrado_em=em_utc(linha.registrado_em), acao=linha.acao,
        origem=linha.origem, entidade=linha.entidade, entidade_id=linha.entidade_id,
        usuario_id=linha.usuario_id, usuario_nome=usuario_nome, motivo=linha.motivo,
        correlation_id=linha.correlation_id, dados_antes=linha.dados_antes,
        dados_depois=linha.dados_depois,
    )


@router.get("", response_model=AuditoriaPagina, summary="Consultar a trilha de auditoria")
def listar_auditorias(
    entidade: str | None = Query(None, max_length=64),
    entidade_id: int | None = Query(None),
    acao: AcaoAuditoria | None = Query(None),
    origem: OrigemAuditoria | None = Query(None),
    usuario_id: int | None = Query(None),
    correlation_id: str | None = Query(None, max_length=64),
    desde: datetime | None = Query(None, description="inclusivo; exige fuso"),
    ate: datetime | None = Query(None, description="exclusivo; exige fuso"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> AuditoriaPagina:
    """Lista auditorias.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    if any(valor is not None and (valor.tzinfo is None or valor.utcoffset() is None)
           for valor in (desde, ate)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="desde e ate exigem fuso horário")
    filtros = []
    for coluna, valor in ((Auditoria.entidade, entidade), (Auditoria.entidade_id, entidade_id),
                          (Auditoria.acao, acao), (Auditoria.origem, origem),
                          (Auditoria.usuario_id, usuario_id),
                          (Auditoria.correlation_id, correlation_id)):
        if valor is not None:
            filtros.append(coluna == valor)
    if desde is not None:
        filtros.append(Auditoria.registrado_em >= desde)
    if ate is not None:
        filtros.append(Auditoria.registrado_em < ate)

    total = db.scalar(select(func.count()).select_from(Auditoria).where(*filtros))
    linhas = db.execute(
        _consulta_base().where(*filtros)
        .order_by(Auditoria.registrado_em.desc(), Auditoria.id.desc())
        .offset((page - 1) * size).limit(size)
    ).all()
    return AuditoriaPagina(
        items=[_resposta(linha, nome) for linha, nome in linhas],
        page=page, size=size, total=total, pages=math.ceil(total / size) if size else 0,
    )


@router.get("/{auditoria_id}", response_model=AuditoriaResposta, summary="Consultar um registro")
def consultar_auditoria(auditoria_id: int, db: Session = Depends(get_db)) -> AuditoriaResposta:
    """Consulta auditoria.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    linha = db.execute(_consulta_base().where(Auditoria.id == auditoria_id)).first()
    if linha is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="registro de auditoria inexistente")
    return _resposta(*linha)
