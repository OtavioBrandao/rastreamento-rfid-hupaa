"""
Camada de serviço do CRUD de leitores, antenas e portais (ISS-012).

Mesmo padrão de `api/service_localizacao.py`: roda contra uma `Session`
recebida por parâmetro, sem dependência de HTTP, e levanta exceções de
DOMÍNIO — nunca `HTTPException`. Mapear domínio para HTTP é do router
(`api/router_hardware.py`).

Modelo de topologia (decisão da issue): a associação portal <-> hardware é
DIRETA na antena (`Antena.portal_id`, nullable). Um leitor pode ter antenas em
portais diferentes; um portal pode agregar antenas de leitores diferentes.
`Leitor.reader_id` (origem no MQTT) é um campo SEPARADO de
`identificador_serial` (número de série de fábrica).

Inativação — DIFERENTE da ISS-011: inativar leitor/antena/portal NUNCA é
bloqueado por `leituras_brutas`/`passagens` (nem por nada): hardware inativo
continua referenciado pelo histórico, e é só um toggle idempotente de `ativo`,
sem cascata e sem checagem de uso. (Já a `ZonaEmUso` da ISS-011 bloqueia por
qualquer referência.) A validação existe na CRIAÇÃO/ASSOCIAÇÃO: antena exige
leitor e zona ativos (e portal ativo, se informado); portal exige as duas zonas
ativas.

`leitores.ativo` (cadastro) é independente de `status`/`ultimo_heartbeat_em`
(conectividade ao vivo, da ingestão): este serviço nunca escreve nestes dois.

Porta do leitor: só a antena ATIVA ocupa a porta (índice único parcial, mesmo
padrão de `uq_tag_ativa`, ISS-010). Inativar libera a porta para uma antena nova;
a linha antiga fica (o histórico a referencia) — então uma porta pode ter várias
linhas, uma ativa e as demais inativas. Consequência para quem resolver
(leitor, porta) -> antena, como a ingestão: filtrar por `ativo`.

PATCH: `atualizar_*` recebe um dict só com o que foi INFORMADO (o router monta
com `model_dump(exclude_unset=True)`) e recusa, com `ValueError`, campo que não
é editável — em particular `Antena.leitor_id`, que é imutável (a antena é
fisicamente cabeada no leitor). `Antena.portal_id` é editável, inclusive para
`None` (desassociar).
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.service_localizacao import TAMANHO_PAGINA_MAXIMO, TAMANHO_PAGINA_PADRAO, Pagina
from db.models import Antena, Leitor, Portal, Zona

# SQLSTATEs do Postgres.
_UNIQUE_VIOLATION = "23505"
_CHECK_VIOLATION = "23514"

# Índice único PARCIAL (WHERE ativo): só a antena ATIVA ocupa a porta do leitor.
# Numa violação de índice único, o Postgres informa o nome do ÍNDICE em
# `diag.constraint_name` (verificado contra o Postgres, não assumido).
_INDICE_PORTA_ATIVA = "uq_antena_ativa_por_porta_leitor"

CAMPOS_EDITAVEIS_LEITOR = frozenset(
    {
        "reader_id",
        "fabricante",
        "modelo",
        "identificador_serial",
        "endereco_rede",
        "parametros_ingestao",
    }
)
# `leitor_id` FICA DE FORA de propósito: a antena é fisicamente cabeada no leitor.
CAMPOS_EDITAVEIS_ANTENA = frozenset({"porta_numero", "zona_associada_id", "funcao", "portal_id"})
CAMPOS_EDITAVEIS_PORTAL = frozenset({"nome", "zona_a_id", "zona_b_id", "localizacao_fisica"})

# Colunas NOT NULL entre as editáveis: "limpar" (None) não faz sentido nelas.
_NAO_NULAVEIS = {
    "reader_id",
    "fabricante",
    "modelo",
    "identificador_serial",
    "porta_numero",
    "zona_associada_id",
    "funcao",
    "nome",
    "zona_a_id",
    "zona_b_id",
}
_TEXTOS_COM_STRIP = {"reader_id", "fabricante", "modelo", "identificador_serial", "nome"}


# --- exceções de domínio -----------------------------------------------------


class ErroHardware(Exception):
    """Base das exceções de domínio deste serviço."""


class LeitorNaoEncontrado(ErroHardware):
    def __init__(self, leitor_id: int) -> None:
        self.leitor_id = leitor_id
        super().__init__(f"Leitor {leitor_id} não encontrado.")


class AntenaNaoEncontrada(ErroHardware):
    def __init__(self, antena_id: int) -> None:
        self.antena_id = antena_id
        super().__init__(f"Antena {antena_id} não encontrada.")


class PortalNaoEncontrado(ErroHardware):
    def __init__(self, portal_id: int) -> None:
        self.portal_id = portal_id
        super().__init__(f"Portal {portal_id} não encontrado.")


class ReaderIdDuplicado(ErroHardware):
    def __init__(self, reader_id: str) -> None:
        self.reader_id = reader_id
        super().__init__(f"Já existe um leitor com reader_id {reader_id!r}.")


class IdentificadorSerialDuplicado(ErroHardware):
    def __init__(self, identificador_serial: str) -> None:
        self.identificador_serial = identificador_serial
        super().__init__(f"Já existe um leitor com identificador_serial {identificador_serial!r}.")


class PortaJaUtilizada(ErroHardware):
    """
    `uq_antena_ativa_por_porta_leitor` (índice único parcial): cada porta física
    do leitor tem no máximo UMA antena ATIVA. Antena inativa não ocupa a porta.
    """

    def __init__(self, leitor_id: int, porta_numero: int) -> None:
        self.leitor_id = leitor_id
        self.porta_numero = porta_numero
        super().__init__(
            f"O leitor {leitor_id} já tem uma antena ATIVA na porta {porta_numero}. "
            "Inative a antena atual antes de usar a porta."
        )


class ZonasDoPortalIguais(ErroHardware):
    """Tradução de `ck_portal_zonas_distintas`: um portal liga DUAS zonas distintas."""

    def __init__(self, zona_id: int | None = None) -> None:
        self.zona_id = zona_id
        super().__init__("zona_a_id e zona_b_id precisam ser zonas distintas.")


class LeitorInvalido(ErroHardware):
    """`leitor_id` de uma antena aponta para leitor inexistente ou inativo."""

    def __init__(self, leitor_id: int, motivo: str) -> None:
        self.leitor_id = leitor_id
        self.motivo = motivo
        super().__init__(f"leitor_id {leitor_id} inválido: {motivo}.")


class ZonaInvalidaParaAntena(ErroHardware):
    def __init__(self, zona_id: int, motivo: str) -> None:
        self.zona_id = zona_id
        self.motivo = motivo
        super().__init__(f"zona_associada_id {zona_id} inválida: {motivo}.")


class PortalInvalido(ErroHardware):
    """`portal_id` de uma antena aponta para portal inexistente ou inativo."""

    def __init__(self, portal_id: int, motivo: str) -> None:
        self.portal_id = portal_id
        self.motivo = motivo
        super().__init__(f"portal_id {portal_id} inválido: {motivo}.")


class ZonaInvalidaParaPortal(ErroHardware):
    def __init__(self, zona_id: int, lado: str, motivo: str) -> None:
        self.zona_id = zona_id
        self.lado = lado
        self.motivo = motivo
        super().__init__(f"{lado} {zona_id} inválida: {motivo}.")


# --- helpers internos ------------------------------------------------------------


def _pgcode(erro: IntegrityError) -> str | None:
    return getattr(erro.orig, "pgcode", None)


def _nome_da_constraint(erro: IntegrityError) -> str:
    return getattr(getattr(erro.orig, "diag", None), "constraint_name", None) or ""


def _commitar(session: Session, traduzir) -> None:
    """
    Commit que traduz `IntegrityError` em exceção de domínio via `traduzir(erro)`
    (devolve a exceção, ou None se não reconhece). O que não for reconhecido
    sobe como está: rotular tudo como "duplicado" esconderia o erro real (FK...).
    Sem o rollback a sessão fica inutilizável ("current transaction is aborted").
    """
    try:
        session.commit()
    except IntegrityError as erro:
        session.rollback()
        traducao = traduzir(erro)
        if traducao is not None:
            raise traducao from erro
        raise


def _paginar(session: Session, modelo, filtros: list, ordem: tuple, page: int, size: int) -> Pagina:
    page = max(1, page)
    size = max(1, min(size, TAMANHO_PAGINA_MAXIMO))

    total = session.scalar(select(func.count()).select_from(modelo).where(*filtros))
    items = session.scalars(
        select(modelo).where(*filtros).order_by(*ordem).offset((page - 1) * size).limit(size)
    ).all()
    return Pagina(items, page, size, total or 0)


def _validar_campos(campos: Mapping[str, Any], permitidos: frozenset[str], nivel: str) -> None:
    """
    Valida um PATCH parcial ANTES de qualquer mutação, para que um PATCH
    inválido nunca deixe o objeto (e a sessão) sujo. `campos` só tem o que foi
    INFORMADO (inclusive `None` explícito = limpar, nas colunas que aceitam).
    Campo fora de `permitidos` é erro de PROGRAMAÇÃO (o schema do router nem o
    expõe): levanta `ValueError` em vez de ignorar em silêncio.
    """
    fora = set(campos) - permitidos
    if fora:
        raise ValueError(f"campo(s) não editável(is) em {nivel}: {sorted(fora)}")
    for campo, valor in campos.items():
        if valor is None and campo in _NAO_NULAVEIS:
            raise ValueError(f"'{campo}' não pode ser None em {nivel}")


def _aplicar_campos(entidade, campos: Mapping[str, Any]) -> None:
    for campo, valor in campos.items():
        if isinstance(valor, str) and campo in _TEXTOS_COM_STRIP:
            valor = valor.strip()
        setattr(entidade, campo, valor)


def _exigir_leitor_ativo(session: Session, leitor_id: int) -> Leitor:
    leitor = session.get(Leitor, leitor_id)
    if leitor is None:
        raise LeitorInvalido(leitor_id, "não existe")
    if not leitor.ativo:
        raise LeitorInvalido(leitor_id, "está inativo")
    return leitor


def _exigir_portal_ativo(session: Session, portal_id: int) -> Portal:
    portal = session.get(Portal, portal_id)
    if portal is None:
        raise PortalInvalido(portal_id, "não existe")
    if not portal.ativo:
        raise PortalInvalido(portal_id, "está inativo")
    return portal


def _exigir_zona_ativa_para_antena(session: Session, zona_id: int) -> Zona:
    zona = session.get(Zona, zona_id)
    if zona is None:
        raise ZonaInvalidaParaAntena(zona_id, "não existe")
    if not zona.ativo:
        raise ZonaInvalidaParaAntena(zona_id, "está inativa")
    return zona


def _exigir_zona_ativa_para_portal(session: Session, zona_id: int, lado: str) -> Zona:
    zona = session.get(Zona, zona_id)
    if zona is None:
        raise ZonaInvalidaParaPortal(zona_id, lado, "não existe")
    if not zona.ativo:
        raise ZonaInvalidaParaPortal(zona_id, lado, "está inativa")
    return zona


# --- leitores ---------------------------------------------------------------------


def _traduzir_leitor(reader_id: str | None, serial: str | None):
    def traduzir(erro: IntegrityError):
        if _pgcode(erro) != _UNIQUE_VIOLATION:
            return None
        constraint = _nome_da_constraint(erro)
        if "reader_id" in constraint:
            return ReaderIdDuplicado(reader_id or "")
        if "identificador_serial" in constraint:
            return IdentificadorSerialDuplicado(serial or "")
        return None

    return traduzir


def criar_leitor(
    session: Session,
    reader_id: str,
    fabricante: str,
    modelo: str,
    identificador_serial: str,
    endereco_rede: str | None = None,
    parametros_ingestao: dict | None = None,
) -> Leitor:
    reader_id = reader_id.strip()
    identificador_serial = identificador_serial.strip()
    leitor = Leitor(
        reader_id=reader_id,
        fabricante=fabricante.strip(),
        modelo=modelo.strip(),
        identificador_serial=identificador_serial,
        endereco_rede=endereco_rede,
        parametros_ingestao=parametros_ingestao,
    )
    session.add(leitor)
    _commitar(session, _traduzir_leitor(reader_id, identificador_serial))
    session.refresh(leitor)
    return leitor


def buscar_leitor_por_id(session: Session, leitor_id: int) -> Leitor:
    leitor = session.get(Leitor, leitor_id)
    if leitor is None:
        raise LeitorNaoEncontrado(leitor_id)
    return leitor


def listar_leitores(
    session: Session,
    page: int = 1,
    size: int = TAMANHO_PAGINA_PADRAO,
    incluir_inativos: bool = False,
) -> Pagina:
    filtros = [] if incluir_inativos else [Leitor.ativo.is_(True)]
    return _paginar(session, Leitor, filtros, (Leitor.reader_id, Leitor.id), page, size)


def atualizar_leitor(session: Session, leitor_id: int, campos: Mapping[str, Any]) -> Leitor:
    leitor = buscar_leitor_por_id(session, leitor_id)
    _validar_campos(campos, CAMPOS_EDITAVEIS_LEITOR, "leitor")
    _aplicar_campos(leitor, campos)
    _commitar(session, _traduzir_leitor(leitor.reader_id, leitor.identificador_serial))
    session.refresh(leitor)
    return leitor


def inativar_leitor(session: Session, leitor_id: int) -> Leitor:
    """Toggle idempotente. Sem cascata para as antenas, sem checagem de histórico."""
    leitor = buscar_leitor_por_id(session, leitor_id)
    if leitor.ativo:
        leitor.ativo = False
        session.commit()
        session.refresh(leitor)
    return leitor


def reativar_leitor(session: Session, leitor_id: int) -> Leitor:
    leitor = buscar_leitor_por_id(session, leitor_id)
    if not leitor.ativo:
        leitor.ativo = True
        session.commit()
        session.refresh(leitor)
    return leitor


# --- portais ------------------------------------------------------------------------


def _traduzir_portal(erro: IntegrityError):
    if _pgcode(erro) == _CHECK_VIOLATION and "ck_portal_zonas_distintas" in _nome_da_constraint(erro):
        return ZonasDoPortalIguais()
    return None


def criar_portal(
    session: Session,
    nome: str,
    zona_a_id: int,
    zona_b_id: int,
    localizacao_fisica: str | None = None,
) -> Portal:
    _exigir_zona_ativa_para_portal(session, zona_a_id, "zona_a_id")
    _exigir_zona_ativa_para_portal(session, zona_b_id, "zona_b_id")

    portal = Portal(
        nome=nome.strip(),
        zona_a_id=zona_a_id,
        zona_b_id=zona_b_id,
        localizacao_fisica=localizacao_fisica,
    )
    session.add(portal)
    # zona_a_id == zona_b_id passa nas duas checagens acima (a mesma zona ativa
    # duas vezes): quem barra é o CHECK do banco, traduzido aqui.
    _commitar(session, _traduzir_portal)
    session.refresh(portal)
    return portal


def buscar_portal_por_id(session: Session, portal_id: int) -> Portal:
    portal = session.get(Portal, portal_id)
    if portal is None:
        raise PortalNaoEncontrado(portal_id)
    return portal


def listar_portais(
    session: Session,
    page: int = 1,
    size: int = TAMANHO_PAGINA_PADRAO,
    incluir_inativos: bool = False,
) -> Pagina:
    filtros = [] if incluir_inativos else [Portal.ativo.is_(True)]
    return _paginar(session, Portal, filtros, (Portal.nome, Portal.id), page, size)


def atualizar_portal(session: Session, portal_id: int, campos: Mapping[str, Any]) -> Portal:
    portal = buscar_portal_por_id(session, portal_id)
    _validar_campos(campos, CAMPOS_EDITAVEIS_PORTAL, "portal")
    for lado in ("zona_a_id", "zona_b_id"):
        if campos.get(lado) is not None:
            _exigir_zona_ativa_para_portal(session, campos[lado], lado)

    _aplicar_campos(portal, campos)
    _commitar(session, _traduzir_portal)
    session.refresh(portal)
    return portal


def inativar_portal(session: Session, portal_id: int) -> Portal:
    """Toggle idempotente. NUNCA bloqueado por `passagens`/antenas que o referenciam."""
    portal = buscar_portal_por_id(session, portal_id)
    if portal.ativo:
        portal.ativo = False
        session.commit()
        session.refresh(portal)
    return portal


def reativar_portal(session: Session, portal_id: int) -> Portal:
    portal = buscar_portal_por_id(session, portal_id)
    if not portal.ativo:
        portal.ativo = True
        session.commit()
        session.refresh(portal)
    return portal


# --- antenas ------------------------------------------------------------------------


def _traduzir_antena(leitor_id: int, porta_numero: int):
    def traduzir(erro: IntegrityError):
        if (
            _pgcode(erro) == _UNIQUE_VIOLATION
            and _nome_da_constraint(erro) == _INDICE_PORTA_ATIVA
        ):
            return PortaJaUtilizada(leitor_id, porta_numero)
        return None

    return traduzir


def criar_antena(
    session: Session,
    leitor_id: int,
    porta_numero: int,
    zona_associada_id: int,
    funcao: str,
    portal_id: int | None = None,
) -> Antena:
    _exigir_leitor_ativo(session, leitor_id)
    _exigir_zona_ativa_para_antena(session, zona_associada_id)
    if portal_id is not None:
        _exigir_portal_ativo(session, portal_id)

    antena = Antena(
        leitor_id=leitor_id,
        porta_numero=porta_numero,
        zona_associada_id=zona_associada_id,
        funcao=funcao,
        portal_id=portal_id,
    )
    session.add(antena)
    _commitar(session, _traduzir_antena(leitor_id, porta_numero))
    session.refresh(antena)
    return antena


def buscar_antena_por_id(session: Session, antena_id: int) -> Antena:
    antena = session.get(Antena, antena_id)
    if antena is None:
        raise AntenaNaoEncontrada(antena_id)
    return antena


def listar_antenas(
    session: Session,
    page: int = 1,
    size: int = TAMANHO_PAGINA_PADRAO,
    incluir_inativos: bool = False,
    leitor_id: int | None = None,
    portal_id: int | None = None,
) -> Pagina:
    filtros = [] if incluir_inativos else [Antena.ativo.is_(True)]
    if leitor_id is not None:
        filtros.append(Antena.leitor_id == leitor_id)
    if portal_id is not None:
        filtros.append(Antena.portal_id == portal_id)
    return _paginar(
        session, Antena, filtros, (Antena.leitor_id, Antena.porta_numero, Antena.id), page, size
    )


def atualizar_antena(session: Session, antena_id: int, campos: Mapping[str, Any]) -> Antena:
    antena = buscar_antena_por_id(session, antena_id)
    _validar_campos(campos, CAMPOS_EDITAVEIS_ANTENA, "antena")
    if campos.get("zona_associada_id") is not None:
        _exigir_zona_ativa_para_antena(session, campos["zona_associada_id"])
    if campos.get("portal_id") is not None:
        _exigir_portal_ativo(session, campos["portal_id"])

    _aplicar_campos(antena, campos)
    _commitar(session, _traduzir_antena(antena.leitor_id, antena.porta_numero))
    session.refresh(antena)
    return antena


def inativar_antena(session: Session, antena_id: int) -> Antena:
    """Toggle idempotente. NUNCA bloqueado por `leituras_brutas`/`passagens`."""
    antena = buscar_antena_por_id(session, antena_id)
    if antena.ativo:
        antena.ativo = False
        session.commit()
        session.refresh(antena)
    return antena


def reativar_antena(session: Session, antena_id: int) -> Antena:
    """
    Idempotente. Como só antena ATIVA ocupa a porta, reativar pode colidir: se
    outra antena ativa já tomou a porta do leitor enquanto esta estava inativa,
    o índice parcial barra e o erro vira `PortaJaUtilizada` (não um erro genérico).
    """
    antena = buscar_antena_por_id(session, antena_id)
    if not antena.ativo:
        antena.ativo = True
        _commitar(session, _traduzir_antena(antena.leitor_id, antena.porta_numero))
        session.refresh(antena)
    return antena
