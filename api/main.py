"""
Aplicação FastAPI do MVP (ISS-008, ISS-009, ISS-010, ISS-011, ISS-012, ISS-026, ISS-027,
ISS-028, ISS-025).

Sobe com:
    uvicorn api.main:app --reload
"""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm.exc import StaleDataError

from api import __version__
from api.auditoria import correlacao_da_requisicao, correlation_id_valido
from api.config_auth import configuracao_auth_do_ambiente
from api.logging_config import configurar_logging_api
from api.router_associacao import router as router_associacao
from api.router_auditoria import router as router_auditoria
from api.router_auth import router as router_auth
from api.router_busca_ativos import router as router_busca_ativos
from api.router_correcoes import router as router_correcoes
from api.router_dashboard import router as router_dashboard
from api.router_equipamento import router as router_equipamento
from api.router_hardware import router as router_hardware
from api.router_leituras import router as router_leituras
from api.router_leituras_laboratorio import router as router_leituras_laboratorio
from api.router_localizacao import router as router_localizacao
from api.router_status_hardware import router as router_status_hardware
from api.router_tipos_equipamento import router as router_tipos_equipamento
from api.router_topologia_portal import router as router_topologia_portal
from api.router_usuarios import router as router_usuarios
from rfid_ingestion.reader_status import StatusPolicy

# Sem isto o uvicorn descarta todo INFO de `api.*` (ver api/logging_config.py).
configurar_logging_api()


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI) -> AsyncIterator[None]:
    # Configuração de autenticação inválida derruba a subida, em vez de só
    # aparecer como 500 no primeiro login.
    """Valida a configuração de autenticação antes de liberar a aplicação ASGI."""
    configuracao_auth_do_ambiente()
    StatusPolicy.from_env()
    yield


app = FastAPI(
    title="Rastreamento RFID HUPAA - API",
    description="API de cadastro do MVP de rastreamento RFID (EASY/HUPAA).",
    version=__version__,
    lifespan=ciclo_de_vida,
)

# tipos_equipamento antes de equipamentos (equipamentos depende dele:
# tipo_id precisa apontar para um tipo existente e ativo), e associacao
# depois de equipamento (associar/substituir tag dependem de o
# equipamento já existir e estar ativo).
app.include_router(router_tipos_equipamento)
app.include_router(router_equipamento)
# ISS-025: correção manual (localização e cadastro), logo depois de equipamentos.
app.include_router(router_correcoes)
app.include_router(router_busca_ativos)
app.include_router(router_dashboard)
app.include_router(router_leituras_laboratorio)
app.include_router(router_leituras)
app.include_router(router_associacao)
app.include_router(router_localizacao)
# hardware depois de localizacao: antena/portal dependem de zonas ativas.
app.include_router(router_status_hardware)
app.include_router(router_hardware)
# topologia logica de portais (ISS-013) apos hardware e localizacao
app.include_router(router_topologia_portal)
# ISS-026: autenticação e administração de usuários. Desde a ISS-027 toda rota
# acima exige sessão e permissão (`api/permissoes.py`, aplicada no APIRouter de
# cada módulo). Públicas: só GET /health, POST /auth/login e POST /auth/logout.
app.include_router(router_auth)
app.include_router(router_usuarios)
# ISS-028: consulta da trilha de auditoria (só leitura, só administrador).
app.include_router(router_auditoria)

CABECALHO_CORRELACAO = "X-Correlation-ID"


@app.middleware("http")
async def correlacao(request: Request, call_next):
    """
    ISS-028: um id por requisição, gravado em toda linha da trilha que ela
    gerar. Usa o do cliente se bem formado; senão gera um. Volta em TODA
    resposta (inclusive 401/403/422) no mesmo header.
    """
    identificador = correlation_id_valido(request.headers.get(CABECALHO_CORRELACAO))
    marca = correlacao_da_requisicao.set(identificador)
    try:
        resposta = await call_next(request)
    finally:
        correlacao_da_requisicao.reset(marca)
    resposta.headers[CABECALHO_CORRELACAO] = identificador
    return resposta

# Campos cujo valor nunca pode voltar no corpo de um 422 (nem em log de erro).
CAMPOS_SENSIVEIS = frozenset(
    {"parametros_ingestao", "senha", "senha_atual", "nova_senha", "senha_temporaria"}
)


def _contem_campo_sensivel(valor: object) -> bool:
    """Um erro de campo AUSENTE traz o objeto inteiro como `input` — com a senha junto."""
    if isinstance(valor, Mapping):
        return any(
            chave in CAMPOS_SENSIVEIS or _contem_campo_sensivel(item)
            for chave, item in valor.items()
        )
    if isinstance(valor, (list, tuple)):
        return any(_contem_campo_sensivel(item) for item in valor)
    return False


@app.exception_handler(StaleDataError)
async def conflito_de_versao(_: Request, __: StaleDataError) -> JSONResponse:
    """
    ISS-025: rede de segurança do `version_id_col` do equipamento. Qualquer
    escrita do ORM que encontre a versão mudada (outra operação gravou no
    meio) vira 409 com o mesmo código da correção, em vez de 500.
    """
    return JSONResponse(status_code=409, content={"detail": {
        "codigo": "conflito_de_versao",
        "mensagem": "O equipamento foi alterado por outra operação. Recarregue e tente de novo.",
    }})


@app.exception_handler(RequestValidationError)
async def erro_de_validacao(_: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Igual ao 422 padrão do FastAPI, com UMA diferença: nos erros de campos
    sensíveis (`CAMPOS_SENSIVEIS`) os campos `input` e `ctx` são removidos.

    Motivo: a barreira de credenciais de `parametros_ingestao`
    (`api/schemas_hardware.py`) rejeita justamente quem tenta mandar uma
    senha/token, e os campos de senha da ISS-026 carregam a própria senha —
    o envelope padrão do Pydantic devolveria esse segredo no corpo da
    resposta (e em qualquer log de erro). Também é removido quando o
    `input` é um objeto que CONTÉM um campo sensível (erro de campo ausente).
    """
    erros = []
    for erro in exc.errors():
        if CAMPOS_SENSIVEIS.intersection(
            item for item in erro.get("loc", ()) if isinstance(item, str)
        ) or _contem_campo_sensivel(erro.get("input")):
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
