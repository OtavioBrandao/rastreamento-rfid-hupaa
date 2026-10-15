"""
Rotas de autenticação (ISS-026): login, logout, me e trocar-senha.

Mapeamento de erro:
- login recusado (qualquer motivo)       -> 401 "credenciais_invalidas", sempre igual
- sem sessão válida                      -> 401 "nao_autenticado"
- senha atual incorreta / conta bloqueada -> 400 "senha_atual_incorreta"
- nova senha igual à atual               -> 422 "nova_senha_igual_a_atual"
"""

from datetime import datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from api import service_auth
from api.config_auth import ConfiguracaoAuth, obter_agora, obter_configuracao_auth
from api.database import get_db
from api.dependencias_auth import NOME_COOKIE, sessao_autenticada
from api.permissoes import lista_de_permissoes
from api.schemas_auth import LoginEntrada, SessaoResposta, TrocarSenhaEntrada, UsuarioResposta
from api.senhas import SenhaForaDaPolitica
from api.timestamps import em_utc
from db.models import Usuario

router = APIRouter(prefix="/auth", tags=["autenticação"])

DETALHE_LOGIN_RECUSADO = "credenciais_invalidas"


def usuario_para_resposta(usuario: Usuario) -> UsuarioResposta:
    """Converte usuário em resposta pública sem hash de senha ou token."""
    return UsuarioResposta(
        id=usuario.id,
        nome=usuario.nome,
        email=usuario.email,
        perfil=usuario.perfil.nome,
        ativo=usuario.ativo,
        deve_trocar_senha=usuario.deve_trocar_senha,
        bloqueado_ate=em_utc(usuario.bloqueado_ate),
        ultimo_login_em=em_utc(usuario.ultimo_login_em),
        created_at=em_utc(usuario.created_at),
        updated_at=em_utc(usuario.updated_at),
    )


def _sessao_para_resposta(sessao: service_auth.SessaoAutenticada) -> SessaoResposta:
    """Monta resposta da sessão com usuário e exigência de troca de senha."""
    return SessaoResposta(
        usuario=usuario_para_resposta(sessao.usuario),
        sessao_expira_em=em_utc(sessao.expira_em),
        permissoes=lista_de_permissoes(sessao.usuario.perfil.nome),
    )


def _apagar_cookie(response: Response, config: ConfiguracaoAuth) -> None:
    """Remove o cookie de autenticação com os atributos de segurança configurados."""
    response.delete_cookie(
        NOME_COOKIE, path="/", secure=config.cookie_seguro, httponly=True, samesite="strict"
    )


@router.post("/login", response_model=SessaoResposta, summary="Entrar com e-mail e senha")
def login(
    payload: LoginEntrada,
    response: Response,
    db: Session = Depends(get_db),
    agora: datetime = Depends(obter_agora),
    config: ConfiguracaoAuth = Depends(obter_configuracao_auth),
) -> SessaoResposta:
    """Autentica credenciais, emite cookie de sessão opaco e devolve o usuário autenticado."""
    try:
        token, sessao = service_auth.autenticar(db, payload.email, payload.senha, agora, config)
    except service_auth.LoginRecusado as erro:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail=DETALHE_LOGIN_RECUSADO
        ) from erro
    db.refresh(sessao.usuario, ["perfil"])
    response.set_cookie(
        NOME_COOKIE,
        token,
        max_age=int(config.sessao_duracao.total_seconds()),
        path="/",
        secure=config.cookie_seguro,
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return _sessao_para_resposta(sessao)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Encerrar a sessão")
def logout(
    rfid_sessao: str | None = Cookie(default=None, include_in_schema=False),
    db: Session = Depends(get_db),
    agora: datetime = Depends(obter_agora),
    config: ConfiguracaoAuth = Depends(obter_configuracao_auth),
) -> Response:
    """Revoga a sessão corrente e remove o cookie de autenticação."""
    service_auth.encerrar_sessao(db, rfid_sessao, agora)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _apagar_cookie(response, config)
    return response


@router.get("/me", response_model=SessaoResposta, summary="Usuário da sessão atual")
def me(
    response: Response,
    sessao: service_auth.SessaoAutenticada = Depends(sessao_autenticada),
) -> SessaoResposta:
    """Devolve usuário e estado da sessão autenticada corrente."""
    response.headers["Cache-Control"] = "no-store"
    return _sessao_para_resposta(sessao)


@router.post(
    "/trocar-senha", status_code=status.HTTP_204_NO_CONTENT, summary="Trocar a própria senha"
)
def trocar_senha(
    payload: TrocarSenhaEntrada,
    sessao: service_auth.SessaoAutenticada = Depends(sessao_autenticada),
    db: Session = Depends(get_db),
    agora: datetime = Depends(obter_agora),
    config: ConfiguracaoAuth = Depends(obter_configuracao_auth),
) -> Response:
    """Valida a senha atual, altera o hash e conclui a troca obrigatória de senha."""
    try:
        service_auth.trocar_senha(
            db, sessao, payload.senha_atual, payload.nova_senha, agora, config
        )
    except service_auth.SenhaAtualIncorreta as erro:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="senha_atual_incorreta"
        ) from erro
    except service_auth.NovaSenhaIgualAtual as erro:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="nova_senha_igual_a_atual"
        ) from erro
    except SenhaForaDaPolitica as erro:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)) from erro
    return Response(status_code=status.HTTP_204_NO_CONTENT)
