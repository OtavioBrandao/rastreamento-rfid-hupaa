"""
Aplicação FastAPI do MVP (ISS-008, ISS-009, ISS-010, ISS-011).

Sobe com:
    uvicorn api.main:app --reload
"""

from fastapi import FastAPI

from api.router_associacao import router as router_associacao
from api.router_equipamento import router as router_equipamento
from api.router_localizacao import router as router_localizacao
from api.router_tipos_equipamento import router as router_tipos_equipamento

app = FastAPI(
    title="RFID Hospital MVP - API",
    description="API de cadastro do MVP de rastreamento RFID (EASY/HUPAA).",
    version="0.1.0",
)

# tipos_equipamento antes de equipamentos (equipamentos depende dele:
# tipo_id precisa apontar para um tipo existente e ativo), e associacao
# depois de equipamento (associar/substituir tag dependem de o
# equipamento já existir e estar ativo).
app.include_router(router_tipos_equipamento)
app.include_router(router_equipamento)
app.include_router(router_associacao)
app.include_router(router_localizacao)


@app.get("/health", tags=["infra"], summary="Liveness check")
def health() -> dict[str, str]:
    """
    Liveness puro: responde sem tocar no banco, de propósito. Um health
    que consulta o Postgres transforma indisponibilidade de banco em
    "aplicação morta" e faz o orquestrador reiniciar um processo que está
    saudável. Readiness com checagem de banco, se for necessário, vira
    endpoint próprio.
    """
    return {"status": "ok"}
