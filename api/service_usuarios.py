"""
Administração de usuários (ISS-026). Só administradores chegam aqui — o
router exige o perfil; este módulo ainda reconfere o autor sob lock.

PROTOCOLO DE LOCKS (obrigatório em toda mudança de usuário):
1. travar o conjunto de administradores ATIVOS, em ordem de id, FOR UPDATE;
2. só depois travar a linha do alvo.
Travar o alvo antes causa deadlock real quando dois admins se rebaixam ao
mesmo tempo (cada um segura a própria linha e espera a do outro). Com a
ordem fixa, o segundo espera o primeiro terminar, relê o conjunto já
atualizado e é recusado — o sistema nunca fica sem administrador ativo.

Os hashes Argon2 são calculados ANTES dos locks: são caros e não dependem
de estado do banco.

Trilha (ISS-028): nada aqui grava `auditorias`. O registro central de
`api/auditoria.py` audita cada flush (criar, atualizar, inativar, reativar,
alterar_senha), com o autor posto na sessão por `sessao_autenticada`.
"""

import math
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from api import senhas
from api.service_auth import PERFIL_ADMINISTRADOR, normalizar_email, revogar_sessoes
from db.models import Perfil, Usuario


class ErroUsuario(Exception):
    """Base das exceções de domínio deste serviço."""


class UsuarioNaoEncontrado(ErroUsuario):
    """Falha de domínio: usuario nao encontrado; traduzida pelo chamador para resposta ou diagnóstico."""
    def __init__(self, usuario_id: int) -> None:
        """Inicializa UsuarioNaoEncontrado com as dependências e valores recebidos."""
        super().__init__(f"Usuário {usuario_id} não encontrado.")


class EmailDuplicado(ErroUsuario):
    """Falha de domínio: email duplicado; traduzida pelo chamador para resposta ou diagnóstico."""
    def __init__(self) -> None:
        """Inicializa EmailDuplicado com as dependências e valores recebidos."""
        super().__init__("Já existe um usuário com este e-mail.")


class UltimoAdministrador(ErroUsuario):
    """Falha de domínio: ultimo administrador; traduzida pelo chamador para resposta ou diagnóstico."""
    def __init__(self) -> None:
        """Inicializa UltimoAdministrador com as dependências e valores recebidos."""
        super().__init__("Operação deixaria o sistema sem administrador ativo.")


class OperacaoNaPropriaConta(ErroUsuario):
    """Falha de domínio: operacao na propria conta; traduzida pelo chamador para resposta ou diagnóstico."""
    def __init__(self, operacao: str) -> None:
        """Inicializa OperacaoNaPropriaConta com as dependências e valores recebidos."""
        super().__init__(f"Um administrador não pode {operacao} a própria conta.")


class AutorSemPermissao(ErroUsuario):
    """O autor perdeu o perfil de administrador enquanto a request esperava o lock."""

    def __init__(self) -> None:
        """Inicializa AutorSemPermissao com as dependências e valores recebidos."""
        super().__init__("acesso_negado")


@dataclass
class PaginaUsuarios:
    """Estrutura Pagina Usuarios usada por api.service_usuarios.

    Campos: items, page, size, total."""
    items: list[Usuario]
    page: int
    size: int
    total: int

    @property
    def pages(self) -> int:
        """Calcula o total de páginas a partir da contagem e do tamanho da página."""
        return math.ceil(self.total / self.size) if self.size else 0


def _perfil_por_nome(db: Session, nome: str) -> Perfil:
    """Obtém o perfil persistido pelo nome aceito pela API."""
    perfil = db.scalar(select(Perfil).where(Perfil.nome == nome))
    if perfil is None:
        # Só acontece se a migration da ISS-026 não foi aplicada.
        raise RuntimeError(f"perfil {nome!r} ausente; aplique as migrations")
    return perfil


def travar_admins_ativos(db: Session) -> list[int]:
    """Passo 1 do protocolo: ids dos admins ativos, travados em ordem de id."""
    return list(db.scalars(
        select(Usuario.id)
        .join(Perfil, Usuario.perfil_id == Perfil.id)
        .where(Perfil.nome == PERFIL_ADMINISTRADOR, Usuario.ativo.is_(True))
        .order_by(Usuario.id)
        .with_for_update(of=Usuario)
    ))


def _travar(db: Session, autor_id: int, alvo_id: int | None) -> tuple[list[int], Usuario | None]:
    """Carrega o usuário sob lock para alteração transacional consistente."""
    admins = travar_admins_ativos(db)
    if autor_id not in admins:
        db.rollback()
        raise AutorSemPermissao()
    if alvo_id is None:
        return admins, None
    alvo = db.scalar(
        select(Usuario)
        .options(joinedload(Usuario.perfil))
        .where(Usuario.id == alvo_id)
        .with_for_update(of=Usuario)
        .execution_options(populate_existing=True)
    )
    if alvo is None:
        db.rollback()
        raise UsuarioNaoEncontrado(alvo_id)
    return admins, alvo


def _impedir_sem_admin(admins: list[int], alvo: Usuario) -> None:
    """Recusa operação que deixaria o sistema sem administrador ativo."""
    if alvo.id in admins and len(admins) == 1:
        raise UltimoAdministrador()


def listar(
    db: Session, page: int, size: int, ativo: bool | None = None, perfil: str | None = None,
) -> PaginaUsuarios:
    """Lista usuarios."""
    filtros = []
    if ativo is not None:
        filtros.append(Usuario.ativo.is_(ativo))
    if perfil is not None:
        filtros.append(Perfil.nome == perfil)
    base = select(Usuario).join(Perfil, Usuario.perfil_id == Perfil.id).where(*filtros)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    items = db.scalars(
        base.options(joinedload(Usuario.perfil))
        .order_by(Usuario.id).offset((page - 1) * size).limit(size)
    ).all()
    return PaginaUsuarios(list(items), page, size, total)


def obter(db: Session, usuario_id: int) -> Usuario:
    """Obtém usuarios."""
    usuario = db.scalar(
        select(Usuario).options(joinedload(Usuario.perfil)).where(Usuario.id == usuario_id)
    )
    if usuario is None:
        raise UsuarioNaoEncontrado(usuario_id)
    return usuario


def criar(
    db: Session, autor_id: int, nome: str, email: str, perfil: str, senha_temporaria: str,
) -> Usuario:
    """Cria usuarios."""
    senhas.validar_politica(senha_temporaria)
    senha_hash = senhas.gerar_hash(senha_temporaria)
    _travar(db, autor_id, None)
    usuario = Usuario(
        nome=nome.strip(),
        email=normalizar_email(email),
        senha_hash=senha_hash,
        perfil=_perfil_por_nome(db, perfil),
        deve_trocar_senha=True,
    )
    db.add(usuario)
    try:
        db.flush()
    except IntegrityError as erro:
        db.rollback()
        raise EmailDuplicado() from erro
    db.commit()
    return obter(db, usuario.id)


def atualizar(
    db: Session, autor_id: int, alvo_id: int, nome: str | None = None, perfil: str | None = None,
) -> Usuario:
    """Atualiza usuarios."""
    admins, alvo = _travar(db, autor_id, alvo_id)
    if perfil is not None and perfil != alvo.perfil.nome:
        if perfil != PERFIL_ADMINISTRADOR:
            try:
                _impedir_sem_admin(admins, alvo)
            except UltimoAdministrador:
                db.rollback()
                raise
        alvo.perfil = _perfil_por_nome(db, perfil)
    if nome is not None:
        alvo.nome = nome.strip()
    db.commit()
    return obter(db, alvo_id)


def desativar(db: Session, autor_id: int, alvo_id: int, agora: datetime) -> Usuario:
    """Desativa usuarios."""
    if autor_id == alvo_id:
        raise OperacaoNaPropriaConta("desativar")
    admins, alvo = _travar(db, autor_id, alvo_id)
    try:
        _impedir_sem_admin(admins, alvo)
    except UltimoAdministrador:
        db.rollback()
        raise
    alvo.ativo = False
    revogar_sessoes(db, alvo.id, agora, "desativacao")
    db.commit()
    return obter(db, alvo_id)


def reativar(db: Session, autor_id: int, alvo_id: int, agora: datetime) -> Usuario:
    """
    Zera o bloqueio. Sessões antigas NÃO voltam: se a conta foi desativada
    por fora da API (UPDATE direto), as sessões dela nunca foram revogadas e
    passariam a valer de novo — por isso são revogadas aqui.
    """
    _admins, alvo = _travar(db, autor_id, alvo_id)
    if not alvo.ativo:
        revogar_sessoes(db, alvo.id, agora, "desativacao")
    alvo.ativo = True
    alvo.tentativas_falhas = 0
    alvo.bloqueado_ate = None
    db.commit()
    return obter(db, alvo_id)


def redefinir_senha(
    db: Session, autor_id: int, alvo_id: int, senha_temporaria: str, agora: datetime,
) -> Usuario:
    """Redefine senha."""
    if autor_id == alvo_id:
        raise OperacaoNaPropriaConta("redefinir a senha de")
    senhas.validar_politica(senha_temporaria)
    senha_hash = senhas.gerar_hash(senha_temporaria)
    _admins, alvo = _travar(db, autor_id, alvo_id)
    alvo.senha_hash = senha_hash
    alvo.deve_trocar_senha = True
    alvo.tentativas_falhas = 0
    alvo.bloqueado_ate = None
    revogar_sessoes(db, alvo.id, agora, "redefinicao_senha")
    db.commit()
    return obter(db, alvo_id)
