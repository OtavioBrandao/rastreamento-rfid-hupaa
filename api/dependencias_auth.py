"""
Dependencies de sessão (ISS-026).

Três níveis, do mais permissivo ao mais restrito:
- `sessao_autenticada`: qualquer sessão válida, inclusive com senha
  temporária. Só /auth/me, /auth/trocar-senha e /auth/logout usam direto.
- `sessao_liberada`: sessão válida SEM troca de senha pendente. Com senha
  temporária responde 403 com detail exatamente "troca_de_senha_obrigatoria"
  — o front da ISS-027 depende desse valor.
- `sessao_administrador`: liberada e com perfil administrador.

O token vem SÓ do cookie `rfid_sessao`; não existe header Authorization.
"""

from datetime import datetime

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.config_auth import obter_agora
from api.database import get_db
from api.service_auth import PERFIL_ADMINISTRADOR, SessaoAutenticada, resolver_sessao

NOME_COOKIE = "rfid_sessao"
DETALHE_NAO_AUTENTICADO = "nao_autenticado"
DETALHE_TROCA_OBRIGATORIA = "troca_de_senha_obrigatoria"
DETALHE_SO_ADMIN = "acesso_restrito_a_administradores"


def sessao_autenticada(
    rfid_sessao: str | None = Cookie(default=None, include_in_schema=False),
    db: Session = Depends(get_db),
    agora: datetime = Depends(obter_agora),
) -> SessaoAutenticada:
    sessao = resolver_sessao(db, rfid_sessao, agora)
    if sessao is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=DETALHE_NAO_AUTENTICADO)
    return sessao


def sessao_liberada(
    sessao: SessaoAutenticada = Depends(sessao_autenticada),
) -> SessaoAutenticada:
    if sessao.usuario.deve_trocar_senha:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=DETALHE_TROCA_OBRIGATORIA)
    return sessao


def sessao_administrador(
    sessao: SessaoAutenticada = Depends(sessao_liberada),
) -> SessaoAutenticada:
    if sessao.usuario.perfil.nome != PERFIL_ADMINISTRADOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=DETALHE_SO_ADMIN)
    return sessao
