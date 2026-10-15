"""
Router HTTP de leitores, antenas e portais (ISS-012).

Responsabilidade única: validar/serializar payload e traduzir as exceções de
domínio de `api.service_hardware` para status code. Nenhuma regra de negócio
mora aqui — mesmo padrão de `api/router_localizacao.py`.

Mapeamento de erro:
- `LeitorNaoEncontrado`/`AntenaNaoEncontrada`/`PortalNaoEncontrado`   -> 404
- `ReaderIdDuplicado`/`IdentificadorSerialDuplicado`/`PortaJaUtilizada` -> 409
- `LeitorInvalido`/`ZonaInvalidaParaAntena`/`PortalInvalido`/
  `ZonaInvalidaParaPortal`/`ZonasDoPortalIguais`                       -> 422
- payload inválido (nome vazio, credencial em parametros_ingestao, null em
  coluna NOT NULL, id <= 0, funcao desconhecida)                        -> 422, pelo Pydantic

Inativar/reativar nunca devolve 409: não há bloqueio por histórico
(`leituras_brutas`/`passagens`) — diferente de `POST /zonas/{id}/inativar`.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api import service_hardware as service
from api.database import get_db
from api.permissoes import Permissao, exigir_por_metodo
from api.schemas_hardware import (
    AntenaAtualizar,
    AntenaCriar,
    AntenaPagina,
    AntenaResposta,
    LeitorAtualizar,
    LeitorCriar,
    LeitorPagina,
    LeitorResposta,
    PortalAtualizar,
    PortalCriar,
    PortalPagina,
    PortalResposta,
)

_PERMISSAO = exigir_por_metodo(
    consultar=Permissao.HARDWARE_CONSULTAR, alterar=Permissao.HARDWARE_ALTERAR
)
router = APIRouter(dependencies=[Depends(_PERMISSAO)])

_NAO_ENCONTRADO = (
    service.LeitorNaoEncontrado,
    service.AntenaNaoEncontrada,
    service.PortalNaoEncontrado,
)
_CONFLITO = (
    service.ReaderIdDuplicado,
    service.IdentificadorSerialDuplicado,
    service.PortaJaUtilizada,
    service.PortalComMapeamentosAtivos,
    service.AntenaComMapeamentoAtivo,
    service.LeitorComMapeamentosAtivos,
)
_ENTIDADE_INVALIDA = (
    service.LeitorInvalido,
    service.ZonaInvalidaParaAntena,
    service.PortalInvalido,
    service.ZonaInvalidaParaPortal,
    service.ZonasDoPortalIguais,
)


def _http(erro: service.ErroHardware) -> HTTPException:
    """Traduz uma exceção de domínio para o HTTPException correspondente."""
    if isinstance(erro, _NAO_ENCONTRADO):
        codigo = status.HTTP_404_NOT_FOUND
    elif isinstance(erro, _CONFLITO):
        codigo = status.HTTP_409_CONFLICT
    elif isinstance(erro, _ENTIDADE_INVALIDA):
        codigo = status.HTTP_422_UNPROCESSABLE_CONTENT
    else:  # pragma: no cover - exceção de domínio nova sem mapeamento explícito
        raise erro
    return HTTPException(codigo, detail=str(erro))


# --- leitores ---------------------------------------------------------------------


@router.post(
    "/leitores",
    response_model=LeitorResposta,
    status_code=status.HTTP_201_CREATED,
    tags=["leitores"],
    summary="Cadastrar leitor",
)
def criar_leitor(payload: LeitorCriar, db: Session = Depends(get_db)) -> service.Leitor:
    """Cria leitor.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.criar_leitor(db, **payload.model_dump())
    except service.ErroHardware as erro:
        raise _http(erro) from erro


@router.get(
    "/leitores",
    response_model=LeitorPagina,
    tags=["leitores"],
    summary="Listar leitores (paginado)",
)
def listar_leitores(
    page: int = Query(1, ge=1),
    size: int = Query(service.TAMANHO_PAGINA_PADRAO, ge=1, le=service.TAMANHO_PAGINA_MAXIMO),
    incluir_inativos: bool = Query(False),
    db: Session = Depends(get_db),
) -> service.Pagina:
    """Lista leitores.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    return service.listar_leitores(db, page=page, size=size, incluir_inativos=incluir_inativos)


@router.get(
    "/leitores/{leitor_id}",
    response_model=LeitorResposta,
    tags=["leitores"],
    summary="Detalhar leitor",
)
def detalhar_leitor(leitor_id: int, db: Session = Depends(get_db)) -> service.Leitor:
    """Obtém os detalhes de leitor.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.buscar_leitor_por_id(db, leitor_id)
    except service.ErroHardware as erro:
        raise _http(erro) from erro


@router.patch(
    "/leitores/{leitor_id}",
    response_model=LeitorResposta,
    tags=["leitores"],
    summary="Atualizar leitor (parcial)",
)
def atualizar_leitor(
    leitor_id: int, payload: LeitorAtualizar, db: Session = Depends(get_db)
) -> service.Leitor:
    """Atualiza leitor.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.atualizar_leitor(db, leitor_id, payload.model_dump(exclude_unset=True))
    except service.ErroHardware as erro:
        raise _http(erro) from erro


@router.post(
    "/leitores/{leitor_id}/inativar",
    response_model=LeitorResposta,
    tags=["leitores"],
    summary="Inativar leitor (baixa lógica; nunca bloqueada pelo histórico)",
)
def inativar_leitor(leitor_id: int, db: Session = Depends(get_db)) -> service.Leitor:
    """Inativa leitor.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.inativar_leitor(db, leitor_id)
    except service.ErroHardware as erro:
        raise _http(erro) from erro


@router.post(
    "/leitores/{leitor_id}/reativar",
    response_model=LeitorResposta,
    tags=["leitores"],
    summary="Reativar leitor",
)
def reativar_leitor(leitor_id: int, db: Session = Depends(get_db)) -> service.Leitor:
    """Reativa leitor.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.reativar_leitor(db, leitor_id)
    except service.ErroHardware as erro:
        raise _http(erro) from erro


# --- antenas ----------------------------------------------------------------------


@router.post(
    "/antenas",
    response_model=AntenaResposta,
    status_code=status.HTTP_201_CREATED,
    tags=["antenas"],
    summary="Cadastrar antena (leitor e zona ativos; portal ativo, se informado)",
)
def criar_antena(payload: AntenaCriar, db: Session = Depends(get_db)) -> service.Antena:
    """Cria antena.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.criar_antena(db, **payload.model_dump())
    except service.ErroHardware as erro:
        raise _http(erro) from erro


@router.get(
    "/antenas",
    response_model=AntenaPagina,
    tags=["antenas"],
    summary="Listar antenas (paginado; filtros opcionais leitor_id e portal_id)",
)
def listar_antenas(
    page: int = Query(1, ge=1),
    size: int = Query(service.TAMANHO_PAGINA_PADRAO, ge=1, le=service.TAMANHO_PAGINA_MAXIMO),
    incluir_inativos: bool = Query(False),
    leitor_id: int | None = Query(None, gt=0),
    portal_id: int | None = Query(None, gt=0),
    db: Session = Depends(get_db),
) -> service.Pagina:
    """Lista antenas.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    return service.listar_antenas(
        db,
        page=page,
        size=size,
        incluir_inativos=incluir_inativos,
        leitor_id=leitor_id,
        portal_id=portal_id,
    )


@router.get(
    "/antenas/{antena_id}",
    response_model=AntenaResposta,
    tags=["antenas"],
    summary="Detalhar antena",
)
def detalhar_antena(antena_id: int, db: Session = Depends(get_db)) -> service.Antena:
    """Obtém os detalhes de antena.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.buscar_antena_por_id(db, antena_id)
    except service.ErroHardware as erro:
        raise _http(erro) from erro


@router.patch(
    "/antenas/{antena_id}",
    response_model=AntenaResposta,
    tags=["antenas"],
    summary="Atualizar antena (parcial; leitor_id é imutável, portal_id aceita null)",
)
def atualizar_antena(
    antena_id: int, payload: AntenaAtualizar, db: Session = Depends(get_db)
) -> service.Antena:
    """Atualiza antena.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.atualizar_antena(db, antena_id, payload.model_dump(exclude_unset=True))
    except service.ErroHardware as erro:
        raise _http(erro) from erro


@router.post(
    "/antenas/{antena_id}/inativar",
    response_model=AntenaResposta,
    tags=["antenas"],
    summary="Inativar antena (baixa lógica; nunca bloqueada pelo histórico)",
)
def inativar_antena(antena_id: int, db: Session = Depends(get_db)) -> service.Antena:
    """Inativa antena.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.inativar_antena(db, antena_id)
    except service.ErroHardware as erro:
        raise _http(erro) from erro


@router.post(
    "/antenas/{antena_id}/reativar",
    response_model=AntenaResposta,
    tags=["antenas"],
    summary="Reativar antena",
)
def reativar_antena(antena_id: int, db: Session = Depends(get_db)) -> service.Antena:
    """Reativa antena.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.reativar_antena(db, antena_id)
    except service.ErroHardware as erro:
        raise _http(erro) from erro


# --- portais ----------------------------------------------------------------------


@router.post(
    "/portais",
    response_model=PortalResposta,
    status_code=status.HTTP_201_CREATED,
    tags=["portais"],
    summary="Cadastrar portal (as duas zonas precisam existir, estar ativas e ser distintas)",
)
def criar_portal(payload: PortalCriar, db: Session = Depends(get_db)) -> service.Portal:
    """Cria portal.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.criar_portal(db, **payload.model_dump())
    except service.ErroHardware as erro:
        raise _http(erro) from erro


@router.get(
    "/portais",
    response_model=PortalPagina,
    tags=["portais"],
    summary="Listar portais (paginado)",
)
def listar_portais(
    page: int = Query(1, ge=1),
    size: int = Query(service.TAMANHO_PAGINA_PADRAO, ge=1, le=service.TAMANHO_PAGINA_MAXIMO),
    incluir_inativos: bool = Query(False),
    db: Session = Depends(get_db),
) -> service.Pagina:
    """Lista portais.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    return service.listar_portais(db, page=page, size=size, incluir_inativos=incluir_inativos)


@router.get(
    "/portais/{portal_id}",
    response_model=PortalResposta,
    tags=["portais"],
    summary="Detalhar portal",
)
def detalhar_portal(portal_id: int, db: Session = Depends(get_db)) -> service.Portal:
    """Obtém os detalhes de portal.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.buscar_portal_por_id(db, portal_id)
    except service.ErroHardware as erro:
        raise _http(erro) from erro


@router.patch(
    "/portais/{portal_id}",
    response_model=PortalResposta,
    tags=["portais"],
    summary="Atualizar portal (parcial)",
)
def atualizar_portal(
    portal_id: int, payload: PortalAtualizar, db: Session = Depends(get_db)
) -> service.Portal:
    """Atualiza portal.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.atualizar_portal(db, portal_id, payload.model_dump(exclude_unset=True))
    except service.ErroHardware as erro:
        raise _http(erro) from erro


@router.post(
    "/portais/{portal_id}/inativar",
    response_model=PortalResposta,
    tags=["portais"],
    summary="Inativar portal (baixa lógica; nunca bloqueada pelo histórico)",
)
def inativar_portal(portal_id: int, db: Session = Depends(get_db)) -> service.Portal:
    """Inativa portal.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.inativar_portal(db, portal_id)
    except service.ErroHardware as erro:
        raise _http(erro) from erro


@router.post(
    "/portais/{portal_id}/reativar",
    response_model=PortalResposta,
    tags=["portais"],
    summary="Reativar portal",
)
def reativar_portal(portal_id: int, db: Session = Depends(get_db)) -> service.Portal:
    """Reativa portal.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.reativar_portal(db, portal_id)
    except service.ErroHardware as erro:
        raise _http(erro) from erro
