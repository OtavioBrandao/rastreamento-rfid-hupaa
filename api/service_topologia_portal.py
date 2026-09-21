"""
Domain service for logical portal topology and antenna mappings (ISS-013).

Answers: 'What does each antenna mean inside that portal?'
Defines logical side (A or B), adjacent zone, and operational function
(entrada, saida, auxiliar) in a temporal, versioned fashion [inicio, fim).

Historical preservation:
- Active mappings have `fim IS NULL`.
- Deactivating sets `fim = now()`.
- Updating sets `old.fim = now()` and creates `new.inicio = now()`, `new.fim = NULL`.
- Past configurations remain queryable for passage and reading interpretation.

Concurrency and invariants:
- Partial unique index `uq_mapeamento_antena_ativo` enforces at most ONE active mapping per antenna.
- Multiple antennas on the same portal side are explicitly allowed.
- Domain checks validate active hardware, correct side/zone matching, and valid functions.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import Antena, Leitor, MapeamentoAntenaPortal, Portal, Zona

_UNIQUE_VIOLATION = "23505"
_INDICE_MAPEAMENTO_ATIVO = "uq_mapeamento_antena_ativo"

LADOS_VALIDOS = frozenset({"a", "b"})
FUNCOES_VALIDAS = frozenset({"entrada", "saida", "auxiliar"})


# --- Domain Exceptions -------------------------------------------------------


class ErroTopologiaPortal(Exception):
    """Base domain exception for portal topology."""


class MapeamentoNaoEncontrado(ErroTopologiaPortal):
    def __init__(self, mapeamento_id: int) -> None:
        self.mapeamento_id = mapeamento_id
        super().__init__(f"Mapeamento {mapeamento_id} não encontrado.")


class PortalNaoEncontrado(ErroTopologiaPortal):
    def __init__(self, portal_id: int) -> None:
        self.portal_id = portal_id
        super().__init__(f"Portal {portal_id} não encontrado.")


class AntenaNaoEncontrada(ErroTopologiaPortal):
    def __init__(self, antena_id: int) -> None:
        self.antena_id = antena_id
        super().__init__(f"Antena {antena_id} não encontrada.")


class PortalInativo(ErroTopologiaPortal):
    def __init__(self, portal_id: int) -> None:
        self.portal_id = portal_id
        super().__init__(f"Portal {portal_id} está inativo.")


class AntenaInativa(ErroTopologiaPortal):
    def __init__(self, antena_id: int) -> None:
        self.antena_id = antena_id
        super().__init__(f"Antena {antena_id} está inativa.")


class AntenaNaoPertenceAoPortal(ErroTopologiaPortal):
    def __init__(self, antena_id: int, portal_esperado_id: int, portal_atual_id: int | None) -> None:
        self.antena_id = antena_id
        self.portal_esperado_id = portal_esperado_id
        self.portal_atual_id = portal_atual_id
        if portal_atual_id is None:
            msg = f"Antena {antena_id} não está associada a nenhum portal (portal_id é null)."
        else:
            msg = f"Antena {antena_id} está associada ao portal {portal_atual_id}, não ao portal {portal_esperado_id}."
        super().__init__(msg)


class LadoInvalido(ErroTopologiaPortal):
    def __init__(self, lado: str) -> None:
        self.lado = lado
        super().__init__(f"Lado {lado!r} inválido. Deve ser 'a' ou 'b'.")


class FuncaoInvalida(ErroTopologiaPortal):
    def __init__(self, funcao: str) -> None:
        self.funcao = funcao
        super().__init__(
            f"Função operacional {funcao!r} inválida. Deve ser 'entrada', 'saida' ou 'auxiliar'."
        )


class ZonaIncompativelComLado(ErroTopologiaPortal):
    def __init__(self, portal_id: int, lado: str, zona_informada_id: int, zona_esperada_id: int) -> None:
        self.portal_id = portal_id
        self.lado = lado
        self.zona_informada_id = zona_informada_id
        self.zona_esperada_id = zona_esperada_id
        super().__init__(
            f"Zona {zona_informada_id} não pertence ao lado '{lado.upper()}' do portal {portal_id} "
            f"(esperado zona {zona_esperada_id})."
        )


class ZonaIncompativelComAntena(ErroTopologiaPortal):
    def __init__(
        self, antena_id: int, zona_antena_id: int, lado: str, zona_lado_id: int
    ) -> None:
        self.antena_id = antena_id
        self.zona_antena_id = zona_antena_id
        self.lado = lado
        self.zona_lado_id = zona_lado_id
        super().__init__(
            f"A antena {antena_id} possui zona_associada_id={zona_antena_id}, que diverge da "
            f"zona {zona_lado_id} configurada no lado '{lado.upper()}' do portal."
        )


class MapeamentoAtivoExistente(ErroTopologiaPortal):
    def __init__(self, antena_id: int, mapeamento_ativo_id: int | None = None) -> None:
        self.antena_id = antena_id
        self.mapeamento_ativo_id = mapeamento_ativo_id
        detalhe = f" (mapeamento id={mapeamento_ativo_id})" if mapeamento_ativo_id else ""
        super().__init__(
            f"A antena {antena_id} já possui um mapeamento lógico ativo{detalhe}. "
            "Inative ou encerre o mapeamento existente antes de criar um novo."
        )


class MapeamentoJaEncerrado(ErroTopologiaPortal):
    def __init__(self, mapeamento_id: int) -> None:
        self.mapeamento_id = mapeamento_id
        super().__init__(
            f"Mapeamento {mapeamento_id} já está encerrado e é histórico (imutável)."
        )


# --- DTOs for Topology Queries ----------------------------------------------


@dataclass(frozen=True)
class ItemTopologiaAntena:
    mapeamento_id: int
    antena_id: int
    reader_id: str
    porta_numero: int
    lado: str
    zona_id: int
    funcao: str
    inicio: datetime


@dataclass(frozen=True)
class TopologiaPortal:
    portal_id: int
    nome: str
    ativo: bool
    zona_a_id: int
    zona_a_nome: str
    zona_b_id: int
    zona_b_nome: str
    antenas: list[ItemTopologiaAntena]


# --- Internal Validation Helpers ---------------------------------------------


def _pgcode(erro: IntegrityError) -> str | None:
    return getattr(erro.orig, "pgcode", None)


def _constraint_name(erro: IntegrityError) -> str:
    return getattr(getattr(erro.orig, "diag", None), "constraint_name", None) or ""


def _commit_mapeamento(session: Session, antena_id: int) -> None:
    """Commit with domain translation for partial unique index conflicts."""
    try:
        session.commit()
    except IntegrityError as erro:
        session.rollback()
        if (
            _pgcode(erro) == _UNIQUE_VIOLATION
            and _INDICE_MAPEAMENTO_ATIVO in _constraint_name(erro)
        ):
            raise MapeamentoAtivoExistente(antena_id) from erro
        raise


def _validar_lado(lado: str) -> str:
    lado_norm = lado.strip().lower()
    if lado_norm not in LADOS_VALIDOS:
        raise LadoInvalido(lado)
    return lado_norm


def _validar_funcao(funcao: str) -> str:
    funcao_norm = funcao.strip().lower()
    if funcao_norm not in FUNCOES_VALIDAS:
        raise FuncaoInvalida(funcao)
    return funcao_norm


def _validar_entidades_e_coerencia(
    session: Session,
    portal_id: int,
    antena_id: int,
    lado_norm: str,
    zona_id: int | None,
) -> tuple[Portal, Antena, int]:
    """
    Validates existence, active states, and cross-entity invariants.
    Returns (portal, antena, resolved_zona_id).
    """
    portal = session.get(Portal, portal_id)
    if portal is None:
        raise PortalNaoEncontrado(portal_id)
    if not portal.ativo:
        raise PortalInativo(portal_id)

    antena = session.get(Antena, antena_id)
    if antena is None:
        raise AntenaNaoEncontrada(antena_id)
    if not antena.ativo:
        raise AntenaInativa(antena_id)

    if antena.portal_id != portal_id:
        raise AntenaNaoPertenceAoPortal(antena_id, portal_id, antena.portal_id)

    zona_lado_esperada = portal.zona_a_id if lado_norm == "a" else portal.zona_b_id

    if zona_id is not None and zona_id != zona_lado_esperada:
        raise ZonaIncompativelComLado(portal_id, lado_norm, zona_id, zona_lado_esperada)

    if antena.zona_associada_id != zona_lado_esperada:
        raise ZonaIncompativelComAntena(
            antena_id, antena.zona_associada_id, lado_norm, zona_lado_esperada
        )

    return portal, antena, zona_lado_esperada


# --- Public Service Operations -----------------------------------------------


def criar_mapeamento(
    session: Session,
    portal_id: int,
    antena_id: int,
    lado: str,
    funcao: str,
    zona_id: int | None = None,
) -> MapeamentoAntenaPortal:
    """
    Creates an active logical antenna mapping inside a portal.

    Validates all 10 domain rules:
    - Active portal and antenna
    - Antenna belongs to this portal
    - Lado in ('a', 'b') and funcao in ('entrada', 'saida', 'auxiliar')
    - Side matches portal zone and antenna associated zone
    - Antenna has no second active mapping
    """
    lado_norm = _validar_lado(lado)
    funcao_norm = _validar_funcao(funcao)

    portal, antena, zona_lado = _validar_entidades_e_coerencia(
        session, portal_id, antena_id, lado_norm, zona_id
    )

    # Check application level duplicate active mapping before DB constraint
    mapeamento_ativo = session.scalar(
        select(MapeamentoAntenaPortal).where(
            MapeamentoAntenaPortal.antena_id == antena_id,
            MapeamentoAntenaPortal.fim.is_(None),
        )
    )
    if mapeamento_ativo is not None:
        raise MapeamentoAtivoExistente(antena_id, mapeamento_ativo.id)

    agora = datetime.now(timezone.utc)
    mapeamento = MapeamentoAntenaPortal(
        antena_id=antena_id,
        portal_id=portal_id,
        lado=lado_norm,
        zona_id=zona_lado,
        funcao=funcao_norm,
        inicio=agora,
        fim=None,
    )
    session.add(mapeamento)
    _commit_mapeamento(session, antena_id)
    session.refresh(mapeamento)
    return mapeamento


def buscar_mapeamento_por_id(session: Session, mapeamento_id: int) -> MapeamentoAntenaPortal:
    mapeamento = session.get(MapeamentoAntenaPortal, mapeamento_id)
    if mapeamento is None:
        raise MapeamentoNaoEncontrado(mapeamento_id)
    return mapeamento


def atualizar_mapeamento(
    session: Session,
    mapeamento_id: int,
    lado: str | None = None,
    funcao: str | None = None,
    zona_id: int | None = None,
) -> MapeamentoAntenaPortal:
    """
    Replaces an active mapping with a new configuration while preserving history.

    Temporal replacement:
    - old.fim = now
    - new.inicio = now, new.fim = NULL
    Executed atomically in a single database transaction.
    """
    mapeamento_atual = buscar_mapeamento_por_id(session, mapeamento_id)
    if mapeamento_atual.fim is not None:
        raise MapeamentoJaEncerrado(mapeamento_id)

    novo_lado = _validar_lado(lado) if lado is not None else mapeamento_atual.lado
    nova_funcao = _validar_funcao(funcao) if funcao is not None else mapeamento_atual.funcao

    portal, antena, zona_lado = _validar_entidades_e_coerencia(
        session, mapeamento_atual.portal_id, mapeamento_atual.antena_id, novo_lado, zona_id
    )

    # If configuration is identical, return existing active mapping
    if (
        novo_lado == mapeamento_atual.lado
        and nova_funcao == mapeamento_atual.funcao
        and zona_lado == mapeamento_atual.zona_id
    ):
        return mapeamento_atual

    agora = datetime.now(timezone.utc)
    mapeamento_atual.fim = agora

    novo_mapeamento = MapeamentoAntenaPortal(
        antena_id=mapeamento_atual.antena_id,
        portal_id=mapeamento_atual.portal_id,
        lado=novo_lado,
        zona_id=zona_lado,
        funcao=nova_funcao,
        inicio=agora,
        fim=None,
    )
    session.add(novo_mapeamento)
    _commit_mapeamento(session, mapeamento_atual.antena_id)
    session.refresh(novo_mapeamento)
    return novo_mapeamento


def inativar_mapeamento(session: Session, mapeamento_id: int) -> MapeamentoAntenaPortal:
    """
    Idempotently deactivates an active mapping by setting `fim = now()`.
    Preserves historical record for future audit and inference.
    """
    mapeamento = buscar_mapeamento_por_id(session, mapeamento_id)
    if mapeamento.fim is None:
        mapeamento.fim = datetime.now(timezone.utc)
        session.commit()
        session.refresh(mapeamento)
    return mapeamento


def listar_mapeamentos_portal(
    session: Session, portal_id: int, incluir_historico: bool = False
) -> list[MapeamentoAntenaPortal]:
    portal = session.get(Portal, portal_id)
    if portal is None:
        raise PortalNaoEncontrado(portal_id)

    stmt = select(MapeamentoAntenaPortal).where(MapeamentoAntenaPortal.portal_id == portal_id)
    if not incluir_historico:
        stmt = stmt.where(MapeamentoAntenaPortal.fim.is_(None))
    stmt = stmt.order_by(MapeamentoAntenaPortal.lado, MapeamentoAntenaPortal.id)
    return list(session.scalars(stmt).all())


def listar_historico_antena(session: Session, antena_id: int) -> list[MapeamentoAntenaPortal]:
    antena = session.get(Antena, antena_id)
    if antena is None:
        raise AntenaNaoEncontrada(antena_id)

    stmt = (
        select(MapeamentoAntenaPortal)
        .where(MapeamentoAntenaPortal.antena_id == antena_id)
        .order_by(MapeamentoAntenaPortal.inicio.desc(), MapeamentoAntenaPortal.id.desc())
    )
    return list(session.scalars(stmt).all())


def obter_topologia_portal(session: Session, portal_id: int) -> TopologiaPortal:
    """
    Loads complete active portal topology required by the inference engine (ISS-015).
    Resolves reader_id and porta_numero in a single query path without multiple roundtrips.
    Only active physical antennas with active logical mappings are included.
    """
    portal = session.get(Portal, portal_id)
    if portal is None:
        raise PortalNaoEncontrado(portal_id)

    zona_a = session.get(Zona, portal.zona_a_id)
    zona_b = session.get(Zona, portal.zona_b_id)

    stmt = (
        select(MapeamentoAntenaPortal, Antena, Leitor)
        .join(Antena, MapeamentoAntenaPortal.antena_id == Antena.id)
        .join(Leitor, Antena.leitor_id == Leitor.id)
        .where(
            MapeamentoAntenaPortal.portal_id == portal_id,
            MapeamentoAntenaPortal.fim.is_(None),
            Antena.ativo.is_(True),
        )
        .order_by(MapeamentoAntenaPortal.lado, Antena.porta_numero, MapeamentoAntenaPortal.id)
    )
    resultados = session.execute(stmt).all()

    itens = [
        ItemTopologiaAntena(
            mapeamento_id=map_obj.id,
            antena_id=map_obj.antena_id,
            reader_id=leitor.reader_id,
            porta_numero=antena.porta_numero,
            lado=map_obj.lado,
            zona_id=map_obj.zona_id,
            funcao=map_obj.funcao,
            inicio=map_obj.inicio,
        )
        for map_obj, antena, leitor in resultados
    ]

    return TopologiaPortal(
        portal_id=portal.id,
        nome=portal.nome,
        ativo=portal.ativo,
        zona_a_id=portal.zona_a_id,
        zona_a_nome=zona_a.nome if zona_a else "",
        zona_b_id=portal.zona_b_id,
        zona_b_nome=zona_b.nome if zona_b else "",
        antenas=itens,
    )
