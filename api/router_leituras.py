"""GET /api/leituras/resumo — presença recente das tags por antena.

Expõe EPCs, equipamentos, antenas e horários: exige sessão e
`laboratorio:consultar` (ISS-027), a mesma permissão das leituras brutas do
laboratório — ambas são leitura de leituras brutas, liberada ao operacional.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.database import get_db
from api.permissoes import Permissao, exigir_por_metodo
from api.service_leituras import resumo

_PERMISSAO = exigir_por_metodo(
    consultar=Permissao.LABORATORIO_CONSULTAR, alterar=Permissao.HARDWARE_ALTERAR
)
router = APIRouter(prefix="/api/leituras", tags=["leituras"], dependencies=[Depends(_PERMISSAO)])


@router.get("/resumo", summary="Contagem recente de leituras por tag e antena")
def resumo_leituras(
    janela_segundos: int = Query(60, ge=5, le=86400),
    somente_cadastradas: bool = Query(False),
    db: Session = Depends(get_db),
) -> dict:
    return resumo(db, now=datetime.now(UTC), janela=timedelta(seconds=janela_segundos),
                  somente_cadastradas=somente_cadastradas)
