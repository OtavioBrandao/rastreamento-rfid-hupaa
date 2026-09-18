"""
Aplicação FastAPI do MVP (ISS-009).

Sobe com:
    uvicorn api.main:app --reload
"""

from fastapi import FastAPI

from api.router_tipos_equipamento import router as router_tipos_equipamento

app = FastAPI(
    title="RFID Hospital MVP - API",
    description="API de cadastro do MVP de rastreamento RFID (EASY/HUPAA).",
    version="0.1.0",
)

app.include_router(router_tipos_equipamento)


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
