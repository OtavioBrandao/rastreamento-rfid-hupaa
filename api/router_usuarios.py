"""
Administração de usuários (ISS-026). TODAS as rotas exigem administrador
com sessão liberada (sem troca de senha pendente).

Mapeamento de erro:
- `UsuarioNaoEncontrado`                         -> 404
- `EmailDuplicado`                               -> 409
- `UltimoAdministrador`                          -> 409
- `OperacaoNaPropriaConta` (desativar/redefinir) -> 409
- `AutorSemPermissao` (rebaixado durante a request) -> 403
- campo extra no corpo (ex.: `email` no PATCH)   -> 422, pelo Pydantic
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api import service_usuarios as service
from api.config_auth import obter_agora
from api.database import get_db
from api.dependencias_auth import sessao_administrador
from api.router_auth import usuario_para_resposta
from api.schemas_auth import (
    NomePerfil,
    RedefinirSenhaEntrada,
    UsuarioAtualizar,
    UsuarioCriar,
    UsuarioPagina,
    UsuarioResposta,
)
from api.senhas import SenhaForaDaPolitica
from api.service_auth import SessaoAutenticada

router = APIRouter(prefix="/usuarios", tags=["usuários"])

_STATUS = {
    service.UsuarioNaoEncontrado: status.HTTP_404_NOT_FOUND,
    service.EmailDuplicado: status.HTTP_409_CONFLICT,
    service.UltimoAdministrador: status.HTTP_409_CONFLICT,
    service.OperacaoNaPropriaConta: status.HTTP_409_CONFLICT,
    service.AutorSemPermissao: status.HTTP_403_FORBIDDEN,
}


def _executar(operacao, *args, **kwargs) -> UsuarioResposta:
    try:
        return usuario_para_resposta(operacao(*args, **kwargs))
    except service.ErroUsuario as erro:
        raise HTTPException(_STATUS[type(erro)], detail=str(erro)) from erro
    except SenhaForaDaPolitica as erro:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)) from erro


@router.get("", response_model=UsuarioPagina, summary="Listar usuários (paginado)")
def listar_usuarios(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    ativo: bool | None = Query(None),
    perfil: NomePerfil | None = Query(None),
    db: Session = Depends(get_db),
    _admin: SessaoAutenticada = Depends(sessao_administrador),
) -> UsuarioPagina:
    pagina = service.listar(db, page=page, size=size, ativo=ativo, perfil=perfil)
    return UsuarioPagina(
        items=[usuario_para_resposta(item) for item in pagina.items],
        page=pagina.page, size=pagina.size, total=pagina.total, pages=pagina.pages,
    )


@router.post(
    "", response_model=UsuarioResposta, status_code=status.HTTP_201_CREATED,
    summary="Criar usuário com senha temporária",
)
def criar_usuario(
    payload: UsuarioCriar,
    db: Session = Depends(get_db),
    admin: SessaoAutenticada = Depends(sessao_administrador),
) -> UsuarioResposta:
    return _executar(
        service.criar, db, admin.usuario.id, nome=payload.nome, email=payload.email,
        perfil=payload.perfil, senha_temporaria=payload.senha_temporaria,
    )


@router.get("/{usuario_id}", response_model=UsuarioResposta, summary="Consultar usuário")
def consultar_usuario(
    usuario_id: int,
    db: Session = Depends(get_db),
    _admin: SessaoAutenticada = Depends(sessao_administrador),
) -> UsuarioResposta:
    return _executar(service.obter, db, usuario_id)


@router.patch("/{usuario_id}", response_model=UsuarioResposta, summary="Editar nome e perfil")
def atualizar_usuario(
    usuario_id: int,
    payload: UsuarioAtualizar,
    db: Session = Depends(get_db),
    admin: SessaoAutenticada = Depends(sessao_administrador),
) -> UsuarioResposta:
    return _executar(
        service.atualizar, db, admin.usuario.id, usuario_id,
        nome=payload.nome, perfil=payload.perfil,
    )


@router.post(
    "/{usuario_id}/desativar", response_model=UsuarioResposta, summary="Desativar usuário"
)
def desativar_usuario(
    usuario_id: int,
    db: Session = Depends(get_db),
    agora: datetime = Depends(obter_agora),
    admin: SessaoAutenticada = Depends(sessao_administrador),
) -> UsuarioResposta:
    return _executar(service.desativar, db, admin.usuario.id, usuario_id, agora)


@router.post(
    "/{usuario_id}/reativar", response_model=UsuarioResposta, summary="Reativar usuário"
)
def reativar_usuario(
    usuario_id: int,
    db: Session = Depends(get_db),
    agora: datetime = Depends(obter_agora),
    admin: SessaoAutenticada = Depends(sessao_administrador),
) -> UsuarioResposta:
    return _executar(service.reativar, db, admin.usuario.id, usuario_id, agora)


@router.post(
    "/{usuario_id}/redefinir-senha", response_model=UsuarioResposta,
    summary="Redefinir senha com nova senha temporária",
)
def redefinir_senha_usuario(
    usuario_id: int,
    payload: RedefinirSenhaEntrada,
    db: Session = Depends(get_db),
    agora: datetime = Depends(obter_agora),
    admin: SessaoAutenticada = Depends(sessao_administrador),
) -> UsuarioResposta:
    return _executar(
        service.redefinir_senha, db, admin.usuario.id, usuario_id,
        payload.senha_temporaria, agora,
    )
