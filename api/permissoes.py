"""
Matriz ÚNICA de permissões do sistema (ISS-027) e as dependencies que a aplicam.

Regras:
- Permissão = recurso + ação (`equipamentos:consultar`). "equipamentos"
  cobre tipos, vínculo de EPC, busca, dashboard e histórico de movimentações.
- NEGADO POR PADRÃO: um perfil fora de `MATRIZ` não tem permissão nenhuma.
- Toda negação é o mesmo 403 `{"detail": "acesso_negado"}` e gera o evento
  `acesso_negado` no logger `api.autorizacao`. Falta de sessão continua sendo
  401 `nao_autenticado` (de `sessao_autenticada`) e não é registrada aqui.
- As duas fábricas partem de `sessao_liberada`: senha temporária barra ANTES
  de qualquer permissão (403 `troca_de_senha_obrigatoria`).

O front não copia esta matriz: `/auth/me` devolve `permissoes` já resolvidas.
"""

import logging
from collections.abc import Callable
from enum import StrEnum

from fastapi import Depends, HTTPException, Request, status

from api.dependencias_auth import sessao_liberada
from api.logging_config import registrar_evento
from api.service_auth import PERFIL_ADMINISTRADOR, PERFIL_OPERACIONAL, SessaoAutenticada

logger = logging.getLogger("api.autorizacao")

DETALHE_ACESSO_NEGADO = "acesso_negado"
METODOS_DE_CONSULTA = frozenset({"GET", "HEAD", "OPTIONS"})


class Permissao(StrEnum):
    EQUIPAMENTOS_CONSULTAR = "equipamentos:consultar"
    EQUIPAMENTOS_ALTERAR = "equipamentos:alterar"
    LOCALIZACAO_CONSULTAR = "localizacao:consultar"
    LOCALIZACAO_ALTERAR = "localizacao:alterar"
    HARDWARE_CONSULTAR = "hardware:consultar"
    HARDWARE_ALTERAR = "hardware:alterar"
    LABORATORIO_CONSULTAR = "laboratorio:consultar"
    USUARIOS_ADMINISTRAR = "usuarios:administrar"


MATRIZ: dict[str, frozenset[Permissao]] = {
    # Consulta tudo, exceto usuários; não altera nada.
    PERFIL_OPERACIONAL: frozenset({
        Permissao.EQUIPAMENTOS_CONSULTAR,
        Permissao.LOCALIZACAO_CONSULTAR,
        Permissao.HARDWARE_CONSULTAR,
        Permissao.LABORATORIO_CONSULTAR,
    }),
    PERFIL_ADMINISTRADOR: frozenset(Permissao),
}


def permissoes_do_perfil(perfil: str) -> frozenset[Permissao]:
    return MATRIZ.get(perfil, frozenset())


def lista_de_permissoes(perfil: str) -> list[str]:
    """Forma pública (ordenada) usada por /auth/me e pelo login."""
    return sorted(permissao.value for permissao in permissoes_do_perfil(perfil))


def _autorizar(request: Request, sessao: SessaoAutenticada, permissao: Permissao) -> None:
    perfil = sessao.usuario.perfil.nome
    if permissao in permissoes_do_perfil(perfil):
        return
    rota = getattr(request.scope.get("route"), "path", None)
    # Só metadados: nunca cookie, token, query string nem corpo.
    registrar_evento(
        logger, "acesso_negado", usuario_id=sessao.usuario.id, perfil=perfil,
        permissao=permissao.value, metodo=request.method, rota=rota,
    )
    raise HTTPException(status.HTTP_403_FORBIDDEN, detail=DETALHE_ACESSO_NEGADO)


def exigir(permissao: Permissao) -> Callable[..., SessaoAutenticada]:
    """Dependency de ROTA (ou de router) que exige uma permissão fixa."""

    def dependencia(
        request: Request, sessao: SessaoAutenticada = Depends(sessao_liberada),
    ) -> SessaoAutenticada:
        _autorizar(request, sessao, permissao)
        return sessao

    dependencia.__name__ = f"exigir_{permissao.name.lower()}"
    dependencia.permissoes_exigidas = frozenset({permissao})
    return dependencia


def exigir_por_metodo(
    *, consultar: Permissao, alterar: Permissao,
) -> Callable[..., SessaoAutenticada]:
    """Dependency de ROUTER: GET/HEAD/OPTIONS exigem `consultar`; o resto, `alterar`."""

    def dependencia(
        request: Request, sessao: SessaoAutenticada = Depends(sessao_liberada),
    ) -> SessaoAutenticada:
        exigida = consultar if request.method in METODOS_DE_CONSULTA else alterar
        _autorizar(request, sessao, exigida)
        return sessao

    dependencia.__name__ = f"exigir_{consultar.name.lower()}_ou_{alterar.name.lower()}"
    dependencia.permissoes_exigidas = frozenset({consultar, alterar})
    dependencia.permissao_consulta = consultar
    dependencia.permissao_alteracao = alterar
    return dependencia


# Objeto ÚNICO usado no router /usuarios e nas rotas que precisam do autor:
# mesma função -> o FastAPI resolve uma vez por request.
administrar_usuarios = exigir(Permissao.USUARIOS_ADMINISTRAR)
