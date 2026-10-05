"""Leituras recentes do portal EASY para observação ao vivo no mapa."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.database import get_db
from api.epc import EpcInvalido, normalizar_epc
from api.laboratorio import PORTAL_LABORATORIO
from api.permissoes import Permissao, exigir_por_metodo
from api.timestamps import em_utc
from db.models import Antena, LeituraBruta, Portal

# Só há leitura; "alterar" fica em hardware:alterar (não existe laboratorio:alterar).
_PERMISSAO = exigir_por_metodo(
    consultar=Permissao.LABORATORIO_CONSULTAR, alterar=Permissao.HARDWARE_ALTERAR
)
router = APIRouter(prefix="/api/laboratorio", tags=["laboratório"], dependencies=[Depends(_PERMISSAO)])


@router.get("/leituras", summary="Leituras recentes das antenas do laboratório")
def leituras_laboratorio(
    after_id: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    epc: str | None = Query(None, min_length=1, max_length=32),
    db: Session = Depends(get_db),
) -> dict:
    if epc is not None:
        try:
            epc = normalizar_epc(epc)
        except EpcInvalido as error:
            raise HTTPException(422, detail=str(error)) from error
    stmt = (select(LeituraBruta.id, LeituraBruta.epc, Antena.porta_numero,
                   LeituraBruta.recebido_em)
            .join(Antena, Antena.id == LeituraBruta.antena_id)
            .join(Portal, Portal.id == Antena.portal_id)
            .where(Portal.nome == PORTAL_LABORATORIO))
    if epc is not None:
        stmt = stmt.where(LeituraBruta.epc == epc)
    if after_id:
        stmt = stmt.where(LeituraBruta.id > after_id).order_by(LeituraBruta.id).limit(limit)
    else:
        stmt = stmt.order_by(LeituraBruta.id.desc()).limit(limit)
    linhas = list(db.execute(stmt).all())
    if not after_id:
        linhas.reverse()
    return {
        "items": [
            {"id": linha.id, "epc": linha.epc, "antena_porta": linha.porta_numero,
             "recebido_em": em_utc(linha.recebido_em).isoformat()}
            for linha in linhas
        ],
        "next_id": linhas[-1].id if linhas else after_id,
    }
