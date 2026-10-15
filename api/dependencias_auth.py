"""
Dependencies de sessão (ISS-026).

Dois níveis de sessão; a permissão por perfil vem por cima, em
`api/permissoes.py` (ISS-027):
- `sessao_autenticada`: qualquer sessão válida, inclusive com senha
  temporária. Só /auth/me e /auth/trocar-senha usam direto.
- `sessao_liberada`: sessão válida SEM troca de senha pendente. Com senha
  temporária responde 403 com detail exatamente "troca_de_senha_obrigatoria"
  — o front depende desse valor. `exigir`/`exigir_por_metodo` partem daqui.

O token vem SÓ do cookie `rfid_sessao`; não existe header Authorization.
"""

from datetime import datetime

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.auditoria import definir_autor
from api.config_auth import obter_agora
from api.database import get_db
from api.service_auth import SessaoAutenticada, resolver_sessao

NOME_COOKIE = "rfid_sessao"
DETALHE_NAO_AUTENTICADO = "nao_autenticado"
DETALHE_TROCA_OBRIGATORIA = "troca_de_senha_obrigatoria"


def sessao_autenticada(
    rfid_sessao: str | None = Cookie(default=None, include_in_schema=False),
    db: Session = Depends(get_db),
    agora: datetime = Depends(obter_agora),
) -> SessaoAutenticada:
    """Resolve cookie de sessão e usuário válido; rejeita credencial ausente ou expirada."""
    sessao = resolver_sessao(db, rfid_sessao, agora)
    if sessao is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=DETALHE_NAO_AUTENTICADO)
    # ISS-028: toda mudança feita nesta request entra na trilha com este autor.
    definir_autor(db, sessao.usuario.id)
    return sessao


def sessao_liberada(
    sessao: SessaoAutenticada = Depends(sessao_autenticada),
) -> SessaoAutenticada:
    """Exige sessão autenticada que já concluiu a troca obrigatória de senha."""
    if sessao.usuario.deve_trocar_senha:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=DETALHE_TROCA_OBRIGATORIA)
    return sessao
