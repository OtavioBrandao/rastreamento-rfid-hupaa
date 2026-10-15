"""
Serviço de autenticação (ISS-026): login, sessão, logout e troca de senha.

Mesmo padrão dos demais serviços: recebe `Session`, levanta exceções de
domínio e não conhece HTTP. O relógio (`agora`) e a configuração chegam por
parâmetro — o router os obtém das dependencies de `api.config_auth`.

Regras de segurança concentradas aqui:
- todo login recusado custa exatamente UMA verificação Argon2 completa,
  exista a conta ou não (hash fictício quando não existe);
- a linha do usuário é travada (`FOR UPDATE`) durante o login e a troca de
  senha, para falhas simultâneas serem todas contadas;
- só o SHA-256 do token vai para o banco.

Ordem de locks: estes caminhos travam UMA única linha de `usuarios` (a do
próprio titular) e nunca esperam por outra, então não formam ciclo com o
protocolo de `api.service_usuarios` (admins ativos em ordem de id, depois o
alvo).
"""

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload

from api import auditoria, senhas
from api.config_auth import ConfiguracaoAuth
from api.logging_config import registrar_evento
from db.models import Sessao, Usuario

logger = logging.getLogger("api.auth")

PERFIL_ADMINISTRADOR = "administrador"
PERFIL_OPERACIONAL = "operacional"
PERFIS = (PERFIL_OPERACIONAL, PERFIL_ADMINISTRADOR)


class LoginRecusado(Exception):
    """Uma única exceção para todos os motivos: o chamador não distingue."""


class SenhaAtualIncorreta(Exception):
    pass


class NovaSenhaIgualAtual(Exception):
    pass


@dataclass
class SessaoAutenticada:
    sessao_id: int
    expira_em: datetime
    usuario: Usuario


def normalizar_email(email: str) -> str:
    return email.strip().lower()


def hash_do_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _usuario_travado_por_email(db: Session, email: str) -> Usuario | None:
    return db.scalar(
        select(Usuario)
        .where(Usuario.email == email)
        .with_for_update(of=Usuario)
        .execution_options(populate_existing=True)
    )


def _usuario_travado_por_id(db: Session, usuario_id: int) -> Usuario:
    return db.scalars(
        select(Usuario)
        .where(Usuario.id == usuario_id)
        .with_for_update(of=Usuario)
        .execution_options(populate_existing=True)
    ).one()


def _bloqueado(usuario: Usuario, agora: datetime) -> bool:
    return usuario.bloqueado_ate is not None and usuario.bloqueado_ate > agora


def _registrar_falha(
    usuario: Usuario, agora: datetime, config: ConfiguracaoAuth,
) -> bool:
    """Conta uma falha seguida; ao atingir o limite, bloqueia e zera. True = bloqueou."""
    usuario.tentativas_falhas += 1
    if usuario.tentativas_falhas < config.login_max_tentativas:
        return False
    usuario.tentativas_falhas = 0
    usuario.bloqueado_ate = agora + config.login_bloqueio
    registrar_evento(
        logger, "conta_bloqueada", usuario_id=usuario.id,
        bloqueado_ate=usuario.bloqueado_ate.isoformat(),
    )
    return True


def autenticar(
    db: Session, email: str, senha: str, agora: datetime, config: ConfiguracaoAuth,
) -> tuple[str, SessaoAutenticada]:
    """Devolve (token em claro, sessão). O token em claro só existe aqui e no cookie."""
    usuario = _usuario_travado_por_email(db, normalizar_email(email))

    if usuario is None:
        senhas.verificar_senha(senhas.hash_ficticio(), senha)
        db.rollback()
        # O e-mail digitado NÃO vai para o log nem para a trilha: é comum
        # digitarem a senha nele. Sem alvo identificável: entidade_id NULL.
        auditoria.registrar(db, "login_recusado", entidade="usuarios", origem="anonimo",
                            motivo="conta_inexistente")
        db.commit()
        registrar_evento(logger, "login_recusado", motivo="conta_inexistente")
        raise LoginRecusado()

    usuario_id = usuario.id
    senha_confere = senhas.verificar_senha(usuario.senha_hash, senha)

    motivo = None
    bloqueou = False
    if not usuario.ativo:
        motivo = "conta_inativa"
    elif _bloqueado(usuario, agora):
        motivo = "conta_bloqueada"
    elif not senha_confere:
        motivo = (
            "senha_incorreta" if senhas.hash_reconhecido(usuario.senha_hash)
            else "hash_invalido"
        )
        bloqueou = _registrar_falha(usuario, agora, config)

    if motivo is not None:
        # Quem tentou não está autenticado: origem anonimo, mesmo com alvo conhecido.
        auditoria.registrar(db, "login_recusado", entidade="usuarios", entidade_id=usuario_id,
                            origem="anonimo", motivo=motivo)
        if bloqueou:
            auditoria.registrar(db, "conta_bloqueada", entidade="usuarios",
                                entidade_id=usuario_id, origem="anonimo",
                                motivo="tentativas_de_login",
                                dados={"bloqueado_ate": usuario.bloqueado_ate.isoformat()})
        db.commit()
        registrar_evento(logger, "login_recusado", usuario_id=usuario_id, motivo=motivo)
        raise LoginRecusado()

    usuario.tentativas_falhas = 0
    usuario.bloqueado_ate = None
    usuario.ultimo_login_em = agora
    token = secrets.token_urlsafe(32)  # 256 bits de entropia
    sessao = Sessao(
        usuario_id=usuario_id,
        token_hash=hash_do_token(token),
        criada_em=agora,
        expira_em=agora + config.sessao_duracao,
    )
    db.add(sessao)
    auditoria.registrar(db, "login_aceito", entidade="usuarios", entidade_id=usuario_id,
                        usuario_id=usuario_id)
    db.commit()
    registrar_evento(logger, "login_aceito", usuario_id=usuario_id, sessao_id=sessao.id)
    return token, SessaoAutenticada(sessao.id, sessao.expira_em, usuario)


def resolver_sessao(db: Session, token: str | None, agora: datetime) -> SessaoAutenticada | None:
    """
    Sessão válida = não revogada, não expirada E usuário ativo. `ativo` é
    conferido a cada request além da revogação feita ao desativar: se a
    conta for desativada direto no banco, a sessão cai do mesmo jeito.
    """
    if not token:
        return None
    sessao = db.scalar(
        select(Sessao)
        .options(joinedload(Sessao.usuario).joinedload(Usuario.perfil))
        .where(Sessao.token_hash == hash_do_token(token))
    )
    if (
        sessao is None
        or sessao.revogada_em is not None
        or sessao.expira_em <= agora
        or not sessao.usuario.ativo
    ):
        return None
    return SessaoAutenticada(sessao.id, sessao.expira_em, sessao.usuario)


def revogar_sessoes(
    db: Session, usuario_id: int, agora: datetime, motivo: str, exceto_sessao_id: int | None = None,
) -> int:
    """Revoga (sem apagar) as sessões abertas do usuário. Não faz commit."""
    condicoes = [Sessao.usuario_id == usuario_id, Sessao.revogada_em.is_(None)]
    if exceto_sessao_id is not None:
        condicoes.append(Sessao.id != exceto_sessao_id)
    resultado = db.execute(
        update(Sessao).where(*condicoes)
        .values(revogada_em=agora, motivo_revogacao=motivo)
        .execution_options(synchronize_session=False)
    )
    return resultado.rowcount


def encerrar_sessao(db: Session, token: str | None, agora: datetime) -> None:
    """Logout idempotente: sem token, token desconhecido ou já revogado não é erro."""
    if not token:
        return
    sessao = db.scalar(
        select(Sessao).where(
            Sessao.token_hash == hash_do_token(token), Sessao.revogada_em.is_(None)
        ).with_for_update()
    )
    if sessao is None:
        db.rollback()
        return
    sessao.revogada_em = agora
    sessao.motivo_revogacao = "logout"
    usuario_id, sessao_id = sessao.usuario_id, sessao.id
    auditoria.registrar(db, "logout", entidade="usuarios", entidade_id=usuario_id,
                        usuario_id=usuario_id)
    db.commit()
    registrar_evento(logger, "logout", usuario_id=usuario_id, sessao_id=sessao_id)


def trocar_senha(
    db: Session,
    sessao: SessaoAutenticada,
    senha_atual: str,
    nova_senha: str,
    agora: datetime,
    config: ConfiguracaoAuth,
) -> None:
    """
    Errar a senha atual conta como falha de login (e pode bloquear a conta):
    uma sessão roubada não vira oráculo ilimitado de senha. Com a conta
    bloqueada, nem a senha certa troca. Sucesso derruba as OUTRAS sessões.
    """
    senhas.validar_politica(nova_senha)
    # Hash novo calculado antes do lock: Argon2 é caro e não precisa da linha.
    novo_hash = senhas.gerar_hash(nova_senha)
    usuario = _usuario_travado_por_id(db, sessao.usuario.id)
    usuario_id = usuario.id

    senha_confere = senhas.verificar_senha(usuario.senha_hash, senha_atual)
    if _bloqueado(usuario, agora):
        db.rollback()
        registrar_evento(
            logger, "troca_senha_recusada", usuario_id=usuario_id, motivo="conta_bloqueada"
        )
        raise SenhaAtualIncorreta()
    if not senha_confere:
        if _registrar_falha(usuario, agora, config):
            auditoria.registrar(db, "conta_bloqueada", entidade="usuarios",
                                entidade_id=usuario_id, usuario_id=usuario_id,
                                motivo="tentativas_de_troca_de_senha",
                                dados={"bloqueado_ate": usuario.bloqueado_ate.isoformat()})
        db.commit()
        registrar_evento(
            logger, "troca_senha_recusada", usuario_id=usuario_id,
            motivo="senha_atual_incorreta",
        )
        raise SenhaAtualIncorreta()
    if nova_senha == senha_atual:
        db.rollback()
        registrar_evento(
            logger, "troca_senha_recusada", usuario_id=usuario_id, motivo="senha_repetida"
        )
        raise NovaSenhaIgualAtual()

    usuario.senha_hash = novo_hash
    usuario.deve_trocar_senha = False
    usuario.tentativas_falhas = 0
    revogadas = revogar_sessoes(
        db, usuario_id, agora, "troca_senha", exceto_sessao_id=sessao.sessao_id
    )
    db.commit()
    registrar_evento(
        logger, "senha_trocada", usuario_id=usuario_id, sessoes_revogadas=revogadas
    )
