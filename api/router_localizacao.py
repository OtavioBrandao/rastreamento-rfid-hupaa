"""
Router HTTP da hierarquia física andar -> setor -> zona (ISS-011, RF-004).

Responsabilidade única: validar/serializar payload e traduzir as exceções
de domínio de `api.service_localizacao` para status code. Nenhuma regra de
negócio mora aqui — mesmo padrão de `api/router_equipamento.py`.

Mapeamento de erro:
- `AndarNaoEncontrado`/`SetorNaoEncontrado`/`ZonaNaoEncontrada` -> 404
- `NomeDuplicado`                                               -> 409
- `TemFilhosAtivos`                                             -> 409
- `ZonaEmUso`                                                   -> 409
- `PaiInativo` (reativar filho com pai inativo)                 -> 409
- `PaiInvalido` (andar/setor pai inexistente ou inativo)        -> 422
- payload inválido (nome vazio, id <= 0)                        -> 422, pelo Pydantic
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api import service_localizacao as service
from api.database import get_db
from api.permissoes import Permissao, exigir_por_metodo
from api.schemas_localizacao import (
    AndarArvore,
    AndarAtualizar,
    AndarCriar,
    AndarPagina,
    AndarResposta,
    SetorAtualizar,
    SetorCriar,
    SetorPagina,
    SetorResposta,
    ZonaAtualizar,
    ZonaCriar,
    ZonaPagina,
    ZonaResposta,
)

_PERMISSAO = exigir_por_metodo(
    consultar=Permissao.LOCALIZACAO_CONSULTAR, alterar=Permissao.LOCALIZACAO_ALTERAR
)
router = APIRouter(dependencies=[Depends(_PERMISSAO)])

_NAO_ENCONTRADO = (
    service.AndarNaoEncontrado,
    service.SetorNaoEncontrado,
    service.ZonaNaoEncontrada,
)
_CONFLITO = (
    service.NomeDuplicado,
    service.TemFilhosAtivos,
    service.ZonaEmUso,
    service.PaiInativo,
)


def _http(erro: service.ErroLocalizacao) -> HTTPException:
    """Traduz uma exceção de domínio para o HTTPException correspondente."""
    if isinstance(erro, _NAO_ENCONTRADO):
        codigo = status.HTTP_404_NOT_FOUND
    elif isinstance(erro, _CONFLITO):
        codigo = status.HTTP_409_CONFLICT
    elif isinstance(erro, service.PaiInvalido):
        codigo = status.HTTP_422_UNPROCESSABLE_CONTENT
    else:  # pragma: no cover - exceção de domínio nova sem mapeamento explícito
        raise erro
    return HTTPException(codigo, detail=str(erro))


# --- árvore -----------------------------------------------------------------------
# Registradas ANTES das rotas /andares/{andar_id}: uma rota de path param
# declarada antes poderia capturar um segmento literal como "arvore".


@router.get(
    "/localizacoes/arvore",
    response_model=list[AndarArvore],
    tags=["localizacao"],
    summary="Árvore completa: andares com setores e zonas aninhados",
)
def arvore_completa(
    incluir_inativos: bool = Query(False), db: Session = Depends(get_db)
) -> list[service.AndarNo]:
    """Consulta a hierarquia completa de andares, setores e zonas para a resposta HTTP."""
    return service.arvore_completa(db, incluir_inativos=incluir_inativos)


@router.get(
    "/andares/{andar_id}/arvore",
    response_model=AndarArvore,
    tags=["localizacao"],
    summary="Árvore de um andar: setores e zonas aninhados",
)
def arvore_do_andar(
    andar_id: int, incluir_inativos: bool = Query(False), db: Session = Depends(get_db)
) -> service.AndarNo:
    """Consulta a árvore de um andar específico ou devolve erro de recurso ausente."""
    try:
        return service.arvore_do_andar(db, andar_id, incluir_inativos=incluir_inativos)
    except service.AndarNaoEncontrado as erro:
        raise _http(erro) from erro


# --- andares ----------------------------------------------------------------------


@router.post(
    "/andares",
    response_model=AndarResposta,
    status_code=status.HTTP_201_CREATED,
    tags=["andares"],
    summary="Cadastrar andar",
)
def criar_andar(payload: AndarCriar, db: Session = Depends(get_db)) -> service.Andar:
    """Cria andar.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.criar_andar(
            db,
            nome=payload.nome,
            descricao=payload.descricao,
            referencia_planta=payload.referencia_planta,
        )
    except service.ErroLocalizacao as erro:
        raise _http(erro) from erro


@router.get(
    "/andares",
    response_model=AndarPagina,
    tags=["andares"],
    summary="Listar andares (paginado)",
)
def listar_andares(
    page: int = Query(1, ge=1),
    size: int = Query(service.TAMANHO_PAGINA_PADRAO, ge=1, le=service.TAMANHO_PAGINA_MAXIMO),
    incluir_inativos: bool = Query(False),
    db: Session = Depends(get_db),
) -> service.Pagina:
    """Lista andares.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    return service.listar_andares(db, page=page, size=size, incluir_inativos=incluir_inativos)


@router.get(
    "/andares/{andar_id}",
    response_model=AndarResposta,
    tags=["andares"],
    summary="Detalhar andar",
)
def detalhar_andar(andar_id: int, db: Session = Depends(get_db)) -> service.Andar:
    """Obtém os detalhes de andar.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.buscar_andar_por_id(db, andar_id)
    except service.ErroLocalizacao as erro:
        raise _http(erro) from erro


@router.patch(
    "/andares/{andar_id}",
    response_model=AndarResposta,
    tags=["andares"],
    summary="Atualizar andar (parcial)",
)
def atualizar_andar(
    andar_id: int, payload: AndarAtualizar, db: Session = Depends(get_db)
) -> service.Andar:
    """Atualiza andar.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.atualizar_andar(
            db,
            andar_id,
            nome=payload.nome,
            descricao=payload.descricao,
            descricao_informada="descricao" in payload.model_fields_set,
            referencia_planta=payload.referencia_planta,
            referencia_planta_informada="referencia_planta" in payload.model_fields_set,
        )
    except service.ErroLocalizacao as erro:
        raise _http(erro) from erro


@router.post(
    "/andares/{andar_id}/inativar",
    response_model=AndarResposta,
    tags=["andares"],
    summary="Inativar andar (baixa lógica; bloqueia se houver setor ativo)",
)
def inativar_andar(andar_id: int, db: Session = Depends(get_db)) -> service.Andar:
    """Inativa andar.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.inativar_andar(db, andar_id)
    except service.ErroLocalizacao as erro:
        raise _http(erro) from erro


@router.post(
    "/andares/{andar_id}/reativar",
    response_model=AndarResposta,
    tags=["andares"],
    summary="Reativar andar",
)
def reativar_andar(andar_id: int, db: Session = Depends(get_db)) -> service.Andar:
    """Reativa andar.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.reativar_andar(db, andar_id)
    except service.ErroLocalizacao as erro:
        raise _http(erro) from erro


# --- setores ----------------------------------------------------------------------


@router.post(
    "/setores",
    response_model=SetorResposta,
    status_code=status.HTTP_201_CREATED,
    tags=["setores"],
    summary="Cadastrar setor (o andar precisa existir e estar ativo)",
)
def criar_setor(payload: SetorCriar, db: Session = Depends(get_db)) -> service.Setor:
    """Cria setor.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.criar_setor(
            db,
            andar_id=payload.andar_id,
            nome=payload.nome,
            descricao=payload.descricao,
            referencia_planta=payload.referencia_planta,
        )
    except service.ErroLocalizacao as erro:
        raise _http(erro) from erro


@router.get(
    "/setores",
    response_model=SetorPagina,
    tags=["setores"],
    summary="Listar setores (paginado; filtro opcional andar_id)",
)
def listar_setores(
    page: int = Query(1, ge=1),
    size: int = Query(service.TAMANHO_PAGINA_PADRAO, ge=1, le=service.TAMANHO_PAGINA_MAXIMO),
    incluir_inativos: bool = Query(False),
    andar_id: int | None = Query(None, gt=0),
    db: Session = Depends(get_db),
) -> service.Pagina:
    """Lista setores.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    return service.listar_setores(
        db, page=page, size=size, incluir_inativos=incluir_inativos, andar_id=andar_id
    )


@router.get(
    "/setores/{setor_id}",
    response_model=SetorResposta,
    tags=["setores"],
    summary="Detalhar setor",
)
def detalhar_setor(setor_id: int, db: Session = Depends(get_db)) -> service.Setor:
    """Obtém os detalhes de setor.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.buscar_setor_por_id(db, setor_id)
    except service.ErroLocalizacao as erro:
        raise _http(erro) from erro


@router.patch(
    "/setores/{setor_id}",
    response_model=SetorResposta,
    tags=["setores"],
    summary="Atualizar setor (parcial)",
)
def atualizar_setor(
    setor_id: int, payload: SetorAtualizar, db: Session = Depends(get_db)
) -> service.Setor:
    """Atualiza setor.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.atualizar_setor(
            db,
            setor_id,
            nome=payload.nome,
            descricao=payload.descricao,
            descricao_informada="descricao" in payload.model_fields_set,
            referencia_planta=payload.referencia_planta,
            referencia_planta_informada="referencia_planta" in payload.model_fields_set,
        )
    except service.ErroLocalizacao as erro:
        raise _http(erro) from erro


@router.post(
    "/setores/{setor_id}/inativar",
    response_model=SetorResposta,
    tags=["setores"],
    summary="Inativar setor (baixa lógica; bloqueia se houver zona ativa)",
)
def inativar_setor(setor_id: int, db: Session = Depends(get_db)) -> service.Setor:
    """Inativa setor.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.inativar_setor(db, setor_id)
    except service.ErroLocalizacao as erro:
        raise _http(erro) from erro


@router.post(
    "/setores/{setor_id}/reativar",
    response_model=SetorResposta,
    tags=["setores"],
    summary="Reativar setor (bloqueia se o andar pai estiver inativo)",
)
def reativar_setor(setor_id: int, db: Session = Depends(get_db)) -> service.Setor:
    """Reativa setor.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.reativar_setor(db, setor_id)
    except service.ErroLocalizacao as erro:
        raise _http(erro) from erro


# --- zonas ------------------------------------------------------------------------


@router.post(
    "/zonas",
    response_model=ZonaResposta,
    status_code=status.HTTP_201_CREATED,
    tags=["zonas"],
    summary="Cadastrar zona (o setor precisa existir e estar ativo)",
)
def criar_zona(payload: ZonaCriar, db: Session = Depends(get_db)) -> service.Zona:
    """Cria zona.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.criar_zona(
            db,
            setor_id=payload.setor_id,
            nome=payload.nome,
            descricao=payload.descricao,
            referencia_planta=payload.referencia_planta,
            observacoes=payload.observacoes,
        )
    except service.ErroLocalizacao as erro:
        raise _http(erro) from erro


@router.get(
    "/zonas",
    response_model=ZonaPagina,
    tags=["zonas"],
    summary="Listar zonas (paginado; filtro opcional setor_id)",
)
def listar_zonas(
    page: int = Query(1, ge=1),
    size: int = Query(service.TAMANHO_PAGINA_PADRAO, ge=1, le=service.TAMANHO_PAGINA_MAXIMO),
    incluir_inativos: bool = Query(False),
    setor_id: int | None = Query(None, gt=0),
    db: Session = Depends(get_db),
) -> service.Pagina:
    """Lista zonas.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    return service.listar_zonas(
        db, page=page, size=size, incluir_inativos=incluir_inativos, setor_id=setor_id
    )


@router.get(
    "/zonas/{zona_id}",
    response_model=ZonaResposta,
    tags=["zonas"],
    summary="Detalhar zona",
)
def detalhar_zona(zona_id: int, db: Session = Depends(get_db)) -> service.Zona:
    """Obtém os detalhes de zona.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.buscar_zona_por_id(db, zona_id)
    except service.ErroLocalizacao as erro:
        raise _http(erro) from erro


@router.patch(
    "/zonas/{zona_id}",
    response_model=ZonaResposta,
    tags=["zonas"],
    summary="Atualizar zona (parcial)",
)
def atualizar_zona(
    zona_id: int, payload: ZonaAtualizar, db: Session = Depends(get_db)
) -> service.Zona:
    """Atualiza zona.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.atualizar_zona(
            db,
            zona_id,
            nome=payload.nome,
            descricao=payload.descricao,
            descricao_informada="descricao" in payload.model_fields_set,
            referencia_planta=payload.referencia_planta,
            referencia_planta_informada="referencia_planta" in payload.model_fields_set,
            observacoes=payload.observacoes,
            observacoes_informada="observacoes" in payload.model_fields_set,
        )
    except service.ErroLocalizacao as erro:
        raise _http(erro) from erro


@router.post(
    "/zonas/{zona_id}/inativar",
    response_model=ZonaResposta,
    tags=["zonas"],
    summary="Inativar zona (baixa lógica; bloqueia se referenciada)",
)
def inativar_zona(zona_id: int, db: Session = Depends(get_db)) -> service.Zona:
    """Inativa zona.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.inativar_zona(db, zona_id)
    except service.ErroLocalizacao as erro:
        raise _http(erro) from erro


@router.post(
    "/zonas/{zona_id}/reativar",
    response_model=ZonaResposta,
    tags=["zonas"],
    summary="Reativar zona (bloqueia se o setor pai estiver inativo)",
)
def reativar_zona(zona_id: int, db: Session = Depends(get_db)) -> service.Zona:
    """Reativa zona.

    Valida o contrato HTTP e as dependências de acesso antes de chamar o serviço."""
    try:
        return service.reativar_zona(db, zona_id)
    except service.ErroLocalizacao as erro:
        raise _http(erro) from erro
