"""
Schemas da autenticação e da administração de usuários (ISS-026).

Nenhum schema de RESPOSTA tem campo de senha ou hash. Nos de entrada, os
campos de senha são os únicos que o handler de 422 de `api.main` protege
(`CAMPOS_SENSIVEIS`) — um nome novo de campo de senha precisa entrar lá.

O login só limita tamanho: validar formato de e-mail ali devolveria 422
para um e-mail e 401 para outro, e a diferença vazaria informação.
"""

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.senhas import TAMANHO_MAXIMO_SENHA, TAMANHO_MINIMO_SENHA

NomePerfil = Literal["operacional", "administrador"]
TAMANHO_MAXIMO_EMAIL = 320
# Só ASCII: a normalização do Python e a CHECK do Postgres (`lower(btrim())`)
# coincidem exatamente para ASCII; para Unicode, a regra de minúsculas difere.
_EMAIL = re.compile(r"^[!-~]+@[!-~]+\.[!-~]+$")

SenhaNova = Annotated[
    str, Field(min_length=TAMANHO_MINIMO_SENHA, max_length=TAMANHO_MAXIMO_SENHA)
]


def _texto_preenchido(valor: str | None) -> str | None:
    if valor is None:
        return None
    valor = valor.strip()
    if not valor:
        raise ValueError("campo não pode ser vazio nem conter apenas espaços")
    return valor


class LoginEntrada(BaseModel):
    email: str = Field(max_length=TAMANHO_MAXIMO_EMAIL)
    senha: str = Field(max_length=1024)


class TrocarSenhaEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    senha_atual: str = Field(max_length=1024)
    nova_senha: SenhaNova


class UsuarioCriar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(max_length=255)
    email: str = Field(max_length=TAMANHO_MAXIMO_EMAIL)
    perfil: NomePerfil
    senha_temporaria: SenhaNova

    _validar_nome = field_validator("nome")(_texto_preenchido)

    @field_validator("email")
    @classmethod
    def _normalizar_email(cls, valor: str) -> str:
        valor = valor.strip().lower()
        if not _EMAIL.fullmatch(valor):
            raise ValueError("e-mail inválido (use o formato nome@dominio, só ASCII)")
        return valor


class UsuarioAtualizar(BaseModel):
    """PATCH só de nome e perfil. E-mail é o login: não é editável (extra → 422)."""

    model_config = ConfigDict(extra="forbid")

    nome: str | None = Field(default=None, max_length=255)
    perfil: NomePerfil | None = None

    @field_validator("nome")
    @classmethod
    def _validar_nome(cls, valor: str | None) -> str:
        if valor is None:
            raise ValueError("nome não pode ser nulo")
        return _texto_preenchido(valor)

    @field_validator("perfil")
    @classmethod
    def _validar_perfil(cls, valor: str | None) -> str:
        if valor is None:
            raise ValueError("perfil não pode ser nulo")
        return valor


class RedefinirSenhaEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    senha_temporaria: SenhaNova


class UsuarioResposta(BaseModel):
    id: int
    nome: str
    email: str
    perfil: NomePerfil
    ativo: bool
    deve_trocar_senha: bool
    bloqueado_ate: datetime | None
    ultimo_login_em: datetime | None
    created_at: datetime
    updated_at: datetime


class UsuarioPagina(BaseModel):
    items: list[UsuarioResposta]
    page: int
    size: int
    total: int
    pages: int


class SessaoResposta(BaseModel):
    usuario: UsuarioResposta
    sessao_expira_em: datetime
