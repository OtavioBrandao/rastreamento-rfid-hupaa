"""
Aplicação FastAPI do MVP (ISS-008, ISS-009, ISS-010, ISS-011, ISS-012).

Sobe com:
    uvicorn api.main:app --reload
"""

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.router_associacao import router as router_associacao
from api.router_busca_ativos import router as router_busca_ativos
from api.router_equipamento import router as router_equipamento
from api.router_hardware import router as router_hardware
from api.router_leituras_laboratorio import router as router_leituras_laboratorio
from api.router_localizacao import router as router_localizacao
from api.router_tipos_equipamento import router as router_tipos_equipamento
from api.router_topologia_portal import router as router_topologia_portal

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
app.include_router(router_busca_ativos)
app.include_router(router_leituras_laboratorio)
app.include_router(router_associacao)
app.include_router(router_localizacao)
# hardware depois de localizacao: antena/portal dependem de zonas ativas.
app.include_router(router_hardware)
# topologia logica de portais (ISS-013) apos hardware e localizacao
app.include_router(router_topologia_portal)


@app.exception_handler(RequestValidationError)
async def erro_de_validacao(_: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Igual ao 422 padrão do FastAPI, com UMA diferença: nos erros de
    `parametros_ingestao` o campo `input` (o valor recebido) é removido.

    Motivo: a barreira de credenciais desse campo (`api/schemas_hardware.py`)
    rejeita justamente quem tenta mandar uma senha/token — e o envelope padrão
    do Pydantic devolveria esse segredo de volta no corpo da resposta (e em
    qualquer log de erro). Rejeitar sem ecoar é o que se espera dela.
    """
    erros = []
    for erro in exc.errors():
        if "parametros_ingestao" in erro.get("loc", ()):
            erro = {chave: valor for chave, valor in erro.items() if chave not in ("input", "ctx")}
        erros.append(erro)
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(erros)})


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
