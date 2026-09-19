"""
Camada de serviço do CRUD da hierarquia física andar -> setor -> zona
(ISS-011, RF-004).

Mesmo padrão de `api/service_tipos_equipamento.py` e
`api/service_equipamento.py`: roda contra uma `Session` recebida por
parâmetro, sem dependência de HTTP, e levanta exceções de DOMÍNIO — nunca
`HTTPException`. Mapear domínio para HTTP é do router
(`api/router_localizacao.py`).

Regras que valem para os três níveis:

- Unicidade por `nome_normalizado` (ver `api/normalizacao.py`) no escopo
  certo, garantida pelo BANCO: andar é único globalmente, setor dentro do
  andar, zona dentro do setor. Nada de SELECT prévio — entre o SELECT e o
  INSERT cabe outra request criando o mesmo nome.
- Baixa é sempre LÓGICA (`ativo = false`), nunca DELETE. Inativar é
  idempotente; reativar também.
- Inativação é de BAIXO PARA CIMA (zona -> setor -> andar): não cascateia.
  Andar/setor com filho ATIVO não inativa. Zona referenciada por qualquer
  linha de portais/antenas/historico/equipamentos não inativa, mesmo que
  quem referencia esteja inativo ou seja histórico (mesmo critério
  "qualquer referência conta" de `TipoEquipamentoEmUso`, ISS-009).
- Criar setor/zona exige pai existente E ativo. Como nas issues
  anteriores, há uma janela (pai inativado entre a checagem e o INSERT)
  aceita para o MVP.
- Reativar é de CIMA PARA BAIXO (andar -> setor -> zona), o espelho da
  inativação: reativar setor/zona com o pai inativo é bloqueado
  (`PaiInativo`). Sem isso ficaria um filho `ativo=true` sob pai inativo,
  que some da árvore padrão (ela filtra pela hierarquia ativa).

`atualizar_*` não move um setor/zona para outro pai: a hierarquia é
imutável depois de criada (mover setor entre andares afetaria as zonas
dele e o que referencia essas zonas — operação própria, fora desta issue).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.normalizacao import normalizar_nome
from db.models import Andar, Antena, Equipamento, HistoricoMovimentacao, Portal, Setor, Zona

TAMANHO_PAGINA_PADRAO = 20
TAMANHO_PAGINA_MAXIMO = 100

# Código SQLSTATE de unique_violation (Postgres).
_SQLSTATE_UNIQUE_VIOLATION = "23505"


# --- exceções de domínio -----------------------------------------------------


class ErroLocalizacao(Exception):
    """Base das exceções de domínio deste serviço."""


class AndarNaoEncontrado(ErroLocalizacao):
    def __init__(self, andar_id: int) -> None:
        self.andar_id = andar_id
        super().__init__(f"Andar {andar_id} não encontrado.")


class SetorNaoEncontrado(ErroLocalizacao):
    def __init__(self, setor_id: int) -> None:
        self.setor_id = setor_id
        super().__init__(f"Setor {setor_id} não encontrado.")


class ZonaNaoEncontrada(ErroLocalizacao):
    def __init__(self, zona_id: int) -> None:
        self.zona_id = zona_id
        super().__init__(f"Zona {zona_id} não encontrada.")


class NomeDuplicado(ErroLocalizacao):
    """`nivel` é 'andar', 'setor' ou 'zona' — o escopo da unicidade muda com ele."""

    _ESCOPO = {
        "andar": "no hospital",
        "setor": "neste andar",
        "zona": "neste setor",
    }

    def __init__(self, nivel: str, nome: str) -> None:
        self.nivel = nivel
        self.nome = nome
        self.nome_normalizado = normalizar_nome(nome)
        super().__init__(
            f"Já existe {nivel} com o nome {nome!r} {self._ESCOPO[nivel]} "
            f"(normalizado: {self.nome_normalizado!r})."
        )


class PaiInvalido(ErroLocalizacao):
    """
    O pai (andar para setor, setor para zona) não existe ou está inativo.
    As duas causas só se distinguem na mensagem — o efeito no chamador
    (422) é o mesmo.
    """

    def __init__(self, nivel_pai: str, pai_id: int, motivo: str) -> None:
        self.nivel_pai = nivel_pai
        self.pai_id = pai_id
        self.motivo = motivo
        super().__init__(f"{nivel_pai}_id {pai_id} inválido: {motivo}.")


class PaiInativo(ErroLocalizacao):
    """
    Reativar um setor/zona cujo pai está inativo. Diferente de `PaiInvalido`
    (criar com pai inexistente/inativo, 422 — o corpo aponta um pai ruim):
    aqui o pedido em si é válido e é o ESTADO que conflita (409).
    """

    def __init__(self, nivel: str, entidade_id: int, nivel_pai: str, pai_id: int) -> None:
        self.nivel = nivel
        self.entidade_id = entidade_id
        self.nivel_pai = nivel_pai
        self.pai_id = pai_id
        super().__init__(
            f"Não é possível reativar {nivel} {entidade_id}: "
            f"o {nivel_pai} pai (id {pai_id}) está inativo. "
            f"Reative o {nivel_pai} primeiro (de cima para baixo: andar, setor, zona)."
        )


class TemFilhosAtivos(ErroLocalizacao):
    def __init__(self, nivel: str, entidade_id: int, nivel_filho: str, total: int) -> None:
        self.nivel = nivel
        self.entidade_id = entidade_id
        self.nivel_filho = nivel_filho
        self.total = total
        super().__init__(
            f"{nivel.capitalize()} {entidade_id} não pode ser inativado: ainda há "
            f"filhos ativos ({nivel_filho}: {total}). "
            "Inative de baixo para cima (zona, setor, andar)."
        )


class ZonaEmUso(ErroLocalizacao):
    def __init__(self, zona_id: int, referenciada_em: str, total: int) -> None:
        self.zona_id = zona_id
        self.referenciada_em = referenciada_em
        self.total = total
        super().__init__(
            f"Zona {zona_id} não pode ser inativada: {total} registro(s) em "
            f"{referenciada_em} ainda referenciam ela."
        )


class Pagina:
    """Resultado paginado dos `listar_*`."""

    def __init__(self, items: Sequence, page: int, size: int, total: int) -> None:
        self.items = list(items)
        self.page = page
        self.size = size
        self.total = total
        self.pages = math.ceil(total / size) if size else 0


# --- helpers internos ------------------------------------------------------------


def _commitar_detectando_duplicidade(session: Session, nivel: str, nome: str) -> None:
    """
    Commit que traduz violação de UNIQUE em `NomeDuplicado`.

    Só `unique_violation` (SQLSTATE 23505) vira NomeDuplicado; qualquer
    outra IntegrityError (ex.: FK) sobe como está — rotular tudo como
    "nome duplicado" esconderia o erro real.
    """
    try:
        session.commit()
    except IntegrityError as erro:
        # Sem o rollback a sessão fica inutilizável ("current transaction
        # is aborted") e o próximo uso estoura por um motivo sem relação.
        session.rollback()
        if getattr(erro.orig, "pgcode", None) == _SQLSTATE_UNIQUE_VIOLATION:
            raise NomeDuplicado(nivel, nome) from erro
        raise


def _paginar(session: Session, modelo, filtros: list, page: int, size: int) -> Pagina:
    page = max(1, page)
    size = max(1, min(size, TAMANHO_PAGINA_MAXIMO))

    total = session.scalar(select(func.count()).select_from(modelo).where(*filtros))
    # `id` desempata: `nome_normalizado` só é único DENTRO do escopo, então
    # uma listagem que cruza escopos (todos os setores, todas as zonas) pode
    # ter nomes iguais, e sem desempate a ordem entre páginas não é estável.
    items = session.scalars(
        select(modelo)
        .where(*filtros)
        .order_by(modelo.nome_normalizado, modelo.id)
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return Pagina(items, page, size, total or 0)


def _aplicar_edicao(
    entidade,
    nome: str | None,
    descricao: str | None,
    descricao_informada: bool,
    referencia_planta: str | None,
    referencia_planta_informada: bool,
) -> None:
    """
    Aplica um PATCH parcial. `descricao_informada`/`referencia_planta_informada`
    resolvem a ambiguidade do None num PATCH ("não mandei o campo" x "mandei
    null para limpar") — quem sabe é o router, via `model_fields_set`.
    """
    if nome is not None:
        nome = nome.strip()
        entidade.nome = nome
        entidade.nome_normalizado = normalizar_nome(nome)
    if descricao_informada:
        entidade.descricao = descricao
    if referencia_planta_informada:
        entidade.referencia_planta = referencia_planta


def _contar(session: Session, modelo, *condicoes) -> int:
    return session.scalar(select(func.count()).select_from(modelo).where(*condicoes)) or 0


def _exigir_andar_ativo(session: Session, andar_id: int) -> Andar:
    andar = session.get(Andar, andar_id)
    if andar is None:
        raise PaiInvalido("andar", andar_id, "não existe")
    if not andar.ativo:
        raise PaiInvalido("andar", andar_id, "está inativo")
    return andar


def _exigir_setor_ativo(session: Session, setor_id: int) -> Setor:
    setor = session.get(Setor, setor_id)
    if setor is None:
        raise PaiInvalido("setor", setor_id, "não existe")
    if not setor.ativo:
        raise PaiInvalido("setor", setor_id, "está inativo")
    return setor


# --- andares ----------------------------------------------------------------------


def criar_andar(
    session: Session,
    nome: str,
    descricao: str | None = None,
    referencia_planta: str | None = None,
) -> Andar:
    nome = nome.strip()
    andar = Andar(
        nome=nome,
        nome_normalizado=normalizar_nome(nome),
        descricao=descricao,
        referencia_planta=referencia_planta,
    )
    session.add(andar)
    _commitar_detectando_duplicidade(session, "andar", nome)
    session.refresh(andar)
    return andar


def buscar_andar_por_id(session: Session, andar_id: int) -> Andar:
    """Busca por id, inclusive inativos."""
    andar = session.get(Andar, andar_id)
    if andar is None:
        raise AndarNaoEncontrado(andar_id)
    return andar


def listar_andares(
    session: Session,
    page: int = 1,
    size: int = TAMANHO_PAGINA_PADRAO,
    incluir_inativos: bool = False,
) -> Pagina:
    filtros = [] if incluir_inativos else [Andar.ativo.is_(True)]
    return _paginar(session, Andar, filtros, page, size)


def atualizar_andar(
    session: Session,
    andar_id: int,
    nome: str | None = None,
    descricao: str | None = None,
    descricao_informada: bool = False,
    referencia_planta: str | None = None,
    referencia_planta_informada: bool = False,
) -> Andar:
    andar = buscar_andar_por_id(session, andar_id)
    _aplicar_edicao(
        andar, nome, descricao, descricao_informada, referencia_planta, referencia_planta_informada
    )
    _commitar_detectando_duplicidade(session, "andar", nome or andar.nome)
    session.refresh(andar)
    return andar


def inativar_andar(session: Session, andar_id: int) -> Andar:
    """Bloqueia se ainda houver setor ATIVO no andar. Idempotente."""
    andar = buscar_andar_por_id(session, andar_id)
    if not andar.ativo:
        return andar

    total = _contar(session, Setor, Setor.andar_id == andar_id, Setor.ativo.is_(True))
    if total:
        raise TemFilhosAtivos("andar", andar_id, "setor", total)

    andar.ativo = False
    session.commit()
    session.refresh(andar)
    return andar


def reativar_andar(session: Session, andar_id: int) -> Andar:
    andar = buscar_andar_por_id(session, andar_id)
    if andar.ativo:
        return andar
    andar.ativo = True
    session.commit()
    session.refresh(andar)
    return andar


# --- setores ----------------------------------------------------------------------


def criar_setor(
    session: Session,
    andar_id: int,
    nome: str,
    descricao: str | None = None,
    referencia_planta: str | None = None,
) -> Setor:
    _exigir_andar_ativo(session, andar_id)

    nome = nome.strip()
    setor = Setor(
        andar_id=andar_id,
        nome=nome,
        nome_normalizado=normalizar_nome(nome),
        descricao=descricao,
        referencia_planta=referencia_planta,
    )
    session.add(setor)
    _commitar_detectando_duplicidade(session, "setor", nome)
    session.refresh(setor)
    return setor


def buscar_setor_por_id(session: Session, setor_id: int) -> Setor:
    setor = session.get(Setor, setor_id)
    if setor is None:
        raise SetorNaoEncontrado(setor_id)
    return setor


def listar_setores(
    session: Session,
    page: int = 1,
    size: int = TAMANHO_PAGINA_PADRAO,
    incluir_inativos: bool = False,
    andar_id: int | None = None,
) -> Pagina:
    filtros = [] if incluir_inativos else [Setor.ativo.is_(True)]
    if andar_id is not None:
        filtros.append(Setor.andar_id == andar_id)
    return _paginar(session, Setor, filtros, page, size)


def atualizar_setor(
    session: Session,
    setor_id: int,
    nome: str | None = None,
    descricao: str | None = None,
    descricao_informada: bool = False,
    referencia_planta: str | None = None,
    referencia_planta_informada: bool = False,
) -> Setor:
    setor = buscar_setor_por_id(session, setor_id)
    _aplicar_edicao(
        setor, nome, descricao, descricao_informada, referencia_planta, referencia_planta_informada
    )
    _commitar_detectando_duplicidade(session, "setor", nome or setor.nome)
    session.refresh(setor)
    return setor


def inativar_setor(session: Session, setor_id: int) -> Setor:
    """Bloqueia se ainda houver zona ATIVA no setor. Idempotente."""
    setor = buscar_setor_por_id(session, setor_id)
    if not setor.ativo:
        return setor

    total = _contar(session, Zona, Zona.setor_id == setor_id, Zona.ativo.is_(True))
    if total:
        raise TemFilhosAtivos("setor", setor_id, "zona", total)

    setor.ativo = False
    session.commit()
    session.refresh(setor)
    return setor


def reativar_setor(session: Session, setor_id: int) -> Setor:
    """Bloqueia se o andar pai estiver inativo. Idempotente."""
    setor = buscar_setor_por_id(session, setor_id)
    if setor.ativo:
        return setor

    andar = session.get(Andar, setor.andar_id)
    if andar is None or not andar.ativo:
        raise PaiInativo("setor", setor_id, "andar", setor.andar_id)

    setor.ativo = True
    session.commit()
    session.refresh(setor)
    return setor


# --- zonas -----------------------------------------------------------------------


def criar_zona(
    session: Session,
    setor_id: int,
    nome: str,
    descricao: str | None = None,
    referencia_planta: str | None = None,
    observacoes: str | None = None,
) -> Zona:
    _exigir_setor_ativo(session, setor_id)

    nome = nome.strip()
    zona = Zona(
        setor_id=setor_id,
        nome=nome,
        nome_normalizado=normalizar_nome(nome),
        descricao=descricao,
        referencia_planta=referencia_planta,
        observacoes=observacoes,
    )
    session.add(zona)
    _commitar_detectando_duplicidade(session, "zona", nome)
    session.refresh(zona)
    return zona


def buscar_zona_por_id(session: Session, zona_id: int) -> Zona:
    zona = session.get(Zona, zona_id)
    if zona is None:
        raise ZonaNaoEncontrada(zona_id)
    return zona


def listar_zonas(
    session: Session,
    page: int = 1,
    size: int = TAMANHO_PAGINA_PADRAO,
    incluir_inativos: bool = False,
    setor_id: int | None = None,
) -> Pagina:
    filtros = [] if incluir_inativos else [Zona.ativo.is_(True)]
    if setor_id is not None:
        filtros.append(Zona.setor_id == setor_id)
    return _paginar(session, Zona, filtros, page, size)


def atualizar_zona(
    session: Session,
    zona_id: int,
    nome: str | None = None,
    descricao: str | None = None,
    descricao_informada: bool = False,
    referencia_planta: str | None = None,
    referencia_planta_informada: bool = False,
    observacoes: str | None = None,
    observacoes_informada: bool = False,
) -> Zona:
    zona = buscar_zona_por_id(session, zona_id)
    _aplicar_edicao(
        zona, nome, descricao, descricao_informada, referencia_planta, referencia_planta_informada
    )
    # `observacoes` (zona morta) só existe na zona, então não passa por
    # `_aplicar_edicao`; mesma regra "não mandei" x "mandei null para limpar".
    if observacoes_informada:
        zona.observacoes = observacoes
    _commitar_detectando_duplicidade(session, "zona", nome or zona.nome)
    session.refresh(zona)
    return zona


def _primeira_referencia_a_zona(session: Session, zona_id: int) -> tuple[str, int] | None:
    """
    Procura, NESTA ORDEM, a primeira tabela com alguma linha apontando para
    a zona, e devolve (descrição da referência, quantidade). Não filtra por
    status de quem referencia: um equipamento inativo, ou um registro de
    histórico antigo, continua precisando resolver a zona.
    """
    consultas = (
        ("equipamentos (ultima_zona_id)", Equipamento, Equipamento.ultima_zona_id == zona_id),
        (
            "portais (zona_a_id/zona_b_id)",
            Portal,
            or_(Portal.zona_a_id == zona_id, Portal.zona_b_id == zona_id),
        ),
        ("antenas (zona_associada_id)", Antena, Antena.zona_associada_id == zona_id),
        (
            "historico_movimentacoes (zona_origem_id/zona_destino_id)",
            HistoricoMovimentacao,
            or_(
                HistoricoMovimentacao.zona_origem_id == zona_id,
                HistoricoMovimentacao.zona_destino_id == zona_id,
            ),
        ),
    )
    for descricao, modelo, condicao in consultas:
        total = _contar(session, modelo, condicao)
        if total:
            return descricao, total
    return None


def inativar_zona(session: Session, zona_id: int) -> Zona:
    """
    Bloqueia se QUALQUER linha de equipamentos.ultima_zona_id, portais,
    antenas ou historico_movimentacoes referenciar a zona. Idempotente.
    """
    zona = buscar_zona_por_id(session, zona_id)
    if not zona.ativo:
        return zona

    referencia = _primeira_referencia_a_zona(session, zona_id)
    if referencia is not None:
        raise ZonaEmUso(zona_id, *referencia)

    zona.ativo = False
    session.commit()
    session.refresh(zona)
    return zona


def reativar_zona(session: Session, zona_id: int) -> Zona:
    """Bloqueia se o setor pai estiver inativo. Idempotente."""
    zona = buscar_zona_por_id(session, zona_id)
    if zona.ativo:
        return zona

    setor = session.get(Setor, zona.setor_id)
    if setor is None or not setor.ativo:
        raise PaiInativo("zona", zona_id, "setor", zona.setor_id)

    zona.ativo = True
    session.commit()
    session.refresh(zona)
    return zona


# --- árvore -----------------------------------------------------------------------
#
# ATENÇÃO (armadilha real): a árvore NÃO é montada carregando `andar.setores`
# com joinedload e depois reatribuindo `andar.setores = [filtrados]`. Isso
# marca os objetos como sujos na sessão e, como `andar_id`/`setor_id` são
# NOT NULL, um autoflush seguinte pode tentar zerar essas FKs e estourar
# IntegrityError numa operação que era só leitura. Aqui cada nível é uma
# query própria (`WHERE andar_id IN (...)`) e o resultado vai para
# dataclasses independentes — as relationships dos objetos ORM carregados
# nunca são tocadas.


@dataclass
class ZonaNo:
    id: int
    setor_id: int
    nome: str
    nome_normalizado: str
    descricao: str | None
    referencia_planta: str | None
    observacoes: str | None
    ativo: bool


@dataclass
class SetorNo:
    id: int
    andar_id: int
    nome: str
    nome_normalizado: str
    descricao: str | None
    referencia_planta: str | None
    ativo: bool
    zonas: list[ZonaNo] = field(default_factory=list)


@dataclass
class AndarNo:
    id: int
    nome: str
    nome_normalizado: str
    descricao: str | None
    referencia_planta: str | None
    ativo: bool
    setores: list[SetorNo] = field(default_factory=list)


def _montar_arvore(
    session: Session, andares: Sequence[Andar], incluir_inativos: bool
) -> list[AndarNo]:
    nos_andar = [
        AndarNo(
            id=a.id,
            nome=a.nome,
            nome_normalizado=a.nome_normalizado,
            descricao=a.descricao,
            referencia_planta=a.referencia_planta,
            ativo=a.ativo,
        )
        for a in andares
    ]
    if not nos_andar:
        return []
    por_andar = {no.id: no for no in nos_andar}

    filtros_setor = [Setor.andar_id.in_(list(por_andar))]
    if not incluir_inativos:
        filtros_setor.append(Setor.ativo.is_(True))
    setores = session.scalars(
        select(Setor).where(*filtros_setor).order_by(Setor.nome_normalizado, Setor.id)
    ).all()

    por_setor: dict[int, SetorNo] = {}
    for s in setores:
        no = SetorNo(
            id=s.id,
            andar_id=s.andar_id,
            nome=s.nome,
            nome_normalizado=s.nome_normalizado,
            descricao=s.descricao,
            referencia_planta=s.referencia_planta,
            ativo=s.ativo,
        )
        por_andar[s.andar_id].setores.append(no)
        por_setor[s.id] = no
    if not por_setor:
        return nos_andar

    filtros_zona = [Zona.setor_id.in_(list(por_setor))]
    if not incluir_inativos:
        filtros_zona.append(Zona.ativo.is_(True))
    zonas = session.scalars(
        select(Zona).where(*filtros_zona).order_by(Zona.nome_normalizado, Zona.id)
    ).all()
    for z in zonas:
        por_setor[z.setor_id].zonas.append(
            ZonaNo(
                id=z.id,
                setor_id=z.setor_id,
                nome=z.nome,
                nome_normalizado=z.nome_normalizado,
                descricao=z.descricao,
                referencia_planta=z.referencia_planta,
                observacoes=z.observacoes,
                ativo=z.ativo,
            )
        )
    return nos_andar


def arvore_completa(session: Session, incluir_inativos: bool = False) -> list[AndarNo]:
    """Todos os andares com setores e zonas aninhados. Esconde inativos por padrão."""
    filtros = [] if incluir_inativos else [Andar.ativo.is_(True)]
    andares = session.scalars(
        select(Andar).where(*filtros).order_by(Andar.nome_normalizado, Andar.id)
    ).all()
    return _montar_arvore(session, andares, incluir_inativos)


def arvore_do_andar(
    session: Session, andar_id: int, incluir_inativos: bool = False
) -> AndarNo:
    """
    Um andar com setores e zonas aninhados. O andar pedido por id é sempre
    devolvido (mesmo inativo — foi pedido explicitamente, como em
    `buscar_andar_por_id`); `incluir_inativos` filtra os DESCENDENTES.
    """
    andar = buscar_andar_por_id(session, andar_id)
    return _montar_arvore(session, [andar], incluir_inativos)[0]
