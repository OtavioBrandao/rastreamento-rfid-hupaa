"""GET /api/leituras/resumo — presença recente das tags por antena."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.database import get_db
from api.service_leituras import resumo

router = APIRouter(prefix="/api/leituras", tags=["leituras"])


@router.get("/resumo", summary="Contagem recente de leituras por tag e antena")
def resumo_leituras(
    janela_segundos: int = Query(60, ge=5, le=86400),
    somente_cadastradas: bool = Query(False),
    db: Session = Depends(get_db),
) -> dict:
    return resumo(db, now=datetime.now(UTC), janela=timedelta(seconds=janela_segundos),
                  somente_cadastradas=somente_cadastradas)
