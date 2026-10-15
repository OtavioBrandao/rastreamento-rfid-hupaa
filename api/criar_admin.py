"""
Cria o primeiro administrador (ISS-026), pelo terminal:

    python -m api.criar_admin --env-file .env.cloud --nome "Fulana" --email fulana@hupaa.example

A senha é pedida por `getpass` duas vezes — nunca por argumento, que
ficaria no histórico do shell e visível em `ps`. Para automação,
`--senha-stdin` lê uma linha da entrada padrão.

Recusa rodar se já existir administrador ativo, a menos que se passe
`--recuperacao` (conta nova de emergência quando ninguém mais consegue
entrar). Este admin NÃO nasce com troca obrigatória: quem digitou a senha
é o próprio titular. A criação é auditada pelo registro central como ação do
sistema (`usuario_id` NULL, origem `sistema`, motivo "comando criar_admin").

Usa a mesma `DATABASE_URL` da API (`api/database.py`).
"""

import argparse
import getpass
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from dotenv import load_dotenv
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api import senhas
from api.auditoria import definir_motivo
from api.schemas_auth import UsuarioCriar
from api.service_auth import PERFIL_ADMINISTRADOR
from api.service_usuarios import travar_admins_ativos
from db.models import Perfil, Usuario

# Chave arbitrária e fixa: serializa duas execuções simultâneas do comando
# quando ainda não há nenhum admin para travar.
_CHAVE_LOCK_BOOTSTRAP = 26_026


class ErroCriarAdmin(Exception):
    """Mensagem segura para o terminal: nunca contém a senha."""


def _analisar_argumentos(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m api.criar_admin", description="Cria o primeiro administrador."
    )
    parser.add_argument("--nome", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--env-file", help="arquivo de ambiente (ex.: .env.cloud ou .env.local)",
    )
    parser.add_argument(
        "--senha-stdin", action="store_true",
        help="lê a senha da primeira linha da entrada padrão (automação)",
    )
    parser.add_argument(
        "--recuperacao", action="store_true",
        help="permite criar mesmo já havendo administrador ativo",
    )
    return parser.parse_args(argv)


def _carregar_ambiente(arquivo: str | None) -> None:
    if arquivo is not None:
        caminho = Path(arquivo)
        if not caminho.is_file():
            raise ErroCriarAdmin("Arquivo de ambiente não encontrado. Verifique --env-file.")
        load_dotenv(caminho, override=True)
    else:
        load_dotenv()
    if not os.environ.get("DATABASE_URL"):
        raise ErroCriarAdmin(
            "DATABASE_URL não definida. Use --env-file .env.cloud ou --env-file .env.local."
        )


def _ler_senha(
    senha_stdin: bool, entrada: TextIO, pedir_senha: Callable[[str], str],
) -> str:
    if senha_stdin:
        senha = entrada.readline().rstrip("\r\n")
    else:
        senha = pedir_senha("Senha: ")
        if pedir_senha("Repita a senha: ") != senha:
            raise ErroCriarAdmin("As senhas digitadas não conferem.")
    try:
        senhas.validar_politica(senha)
    except senhas.SenhaForaDaPolitica as erro:
        raise ErroCriarAdmin(f"Senha recusada: {erro}.") from None
    return senha


def _validar_dados(nome: str, email: str) -> tuple[str, str]:
    """Reaproveita as regras do schema da API, sem senha envolvida."""
    try:
        dados = UsuarioCriar(
            nome=nome, email=email, perfil=PERFIL_ADMINISTRADOR,
            senha_temporaria="x" * senhas.TAMANHO_MINIMO_SENHA,
        )
    except ValueError as erro:
        campos = sorted({str(item["loc"][0]) for item in erro.errors()})
        raise ErroCriarAdmin(f"Dados inválidos: {', '.join(campos)}.") from None
    return dados.nome, dados.email


def criar_administrador(
    db: Session, nome: str, email: str, senha: str, recuperacao: bool,
) -> Usuario:
    senha_hash = senhas.gerar_hash(senha)
    db.execute(text("SELECT pg_advisory_xact_lock(:chave)"), {"chave": _CHAVE_LOCK_BOOTSTRAP})
    if travar_admins_ativos(db) and not recuperacao:
        db.rollback()
        raise ErroCriarAdmin(
            "Já existe administrador ativo. Use a API, ou --recuperacao em emergência."
        )
    perfil = db.scalar(select(Perfil).where(Perfil.nome == PERFIL_ADMINISTRADOR))
    if perfil is None:
        db.rollback()
        raise ErroCriarAdmin("Perfil administrador ausente: aplique as migrations.")
    usuario = Usuario(
        nome=nome, email=email, senha_hash=senha_hash, perfil=perfil, deve_trocar_senha=False,
    )
    # Sem autor (origem sistema): a trilha `criar` sai do registro central com este motivo.
    definir_motivo(db, "comando criar_admin (recuperação de acesso)" if recuperacao
                   else "comando criar_admin")
    db.add(usuario)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ErroCriarAdmin("Já existe um usuário com este e-mail.") from None
    db.commit()
    return usuario


def main(
    argv: list[str] | None = None,
    *,
    session_factory: Callable[[], Session] | None = None,
    entrada: TextIO | None = None,
    pedir_senha: Callable[[str], str] = getpass.getpass,
    saida: TextIO | None = None,
) -> int:
    args = _analisar_argumentos(argv)
    saida = saida or sys.stdout
    try:
        nome, email = _validar_dados(args.nome, args.email)
        if session_factory is None:
            _carregar_ambiente(args.env_file)
            from api.database import SessionLocal

            session_factory = SessionLocal
        senha = _ler_senha(args.senha_stdin, entrada or sys.stdin, pedir_senha)
        db = session_factory()
        try:
            usuario = criar_administrador(db, nome, email, senha, args.recuperacao)
            usuario_id, usuario_email = usuario.id, usuario.email
        finally:
            db.close()
    except ErroCriarAdmin as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    print(f"Administrador criado: id={usuario_id} email={usuario_email}", file=saida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
