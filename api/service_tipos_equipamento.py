"""
Camada de serviço do CRUD de tipos de equipamento (ISS-009).

Separada do router de propósito: tudo aqui roda contra uma `Session`
recebida por parâmetro, sem nenhuma dependência de HTTP. Isso permite
testar as regras de negócio contra um Postgres de verdade sem subir a
API, e mantém o router como tradutor fino de exceção -> status code.

Contrato de erro: esta camada levanta exceções de DOMÍNIO, nunca
`HTTPException`. Mapear domínio para HTTP é responsabilidade do router
(`api/router_tipos_equipamento.py`).
"""

import math
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.normalizacao import normalizar_nome
from db.models import Equipamento, TipoEquipamento

TAMANHO_PAGINA_PADRAO = 20
TAMANHO_PAGINA_MAXIMO = 100


class ErroTipoEquipamento(Exception):
    """Base das exceções de domínio deste serviço."""


class TipoEquipamentoNaoEncontrado(ErroTipoEquipamento):
    """Falha de domínio: tipo equipamento nao encontrado; traduzida pelo chamador para resposta ou diagnóstico."""
    def __init__(self, tipo_id: int) -> None:
        """Inicializa TipoEquipamentoNaoEncontrado com as dependências e valores recebidos."""
        self.tipo_id = tipo_id
        super().__init__(f"Tipo de equipamento {tipo_id} não encontrado.")


class NomeDuplicado(ErroTipoEquipamento):
    """Falha de domínio: nome duplicado; traduzida pelo chamador para resposta ou diagnóstico."""
    def __init__(self, nome: str) -> None:
        """Inicializa NomeDuplicado com as dependências e valores recebidos."""
        self.nome = nome
        self.nome_normalizado = normalizar_nome(nome)
        super().__init__(
            f"Já existe um tipo de equipamento com o nome {nome!r} "
            f"(normalizado: {self.nome_normalizado!r})."
        )


class TipoEquipamentoEmUso(ErroTipoEquipamento):
    """Falha de domínio: tipo equipamento em uso; traduzida pelo chamador para resposta ou diagnóstico."""
    def __init__(self, tipo_id: int, total_equipamentos: int) -> None:
        """Inicializa TipoEquipamentoEmUso com as dependências e valores recebidos."""
        self.tipo_id = tipo_id
        self.total_equipamentos = total_equipamentos
        super().__init__(
            f"Tipo de equipamento {tipo_id} não pode ser inativado: "
            f"{total_equipamentos} equipamento(s) ainda apontam para ele."
        )


class PaginaTipos:
    """Resultado paginado de `listar`."""

    def __init__(
        self,
        items: Sequence[TipoEquipamento],
        page: int,
        size: int,
        total: int,
    ) -> None:
        """Inicializa PaginaTipos com as dependências e valores recebidos."""
        self.items = list(items)
        self.page = page
        self.size = size
        self.total = total
        self.pages = math.ceil(total / size) if size else 0


def criar(session: Session, nome: str, descricao: str | None = None) -> TipoEquipamento:
    """
    Cadastra um tipo novo.

    A detecção de duplicidade é delegada ao UNIQUE do banco, não a um
    SELECT prévio: entre o SELECT e o INSERT cabe outra request criando o
    mesmo nome, e aí o "não existe" seria mentira. O banco é o único
    ponto que decide isso sem corrida.
    """
    nome = nome.strip()
    tipo = TipoEquipamento(
        nome=nome,
        nome_normalizado=normalizar_nome(nome),
        descricao=descricao,
    )
    session.add(tipo)
    try:
        session.commit()
    except IntegrityError as erro:
        # Sem o rollback a sessão fica inutilizável ("current transaction
        # is aborted") e o próximo uso dela estoura por um motivo que não
        # tem nada a ver com o erro real.
        session.rollback()
        raise NomeDuplicado(nome) from erro
    session.refresh(tipo)
    return tipo


def buscar_por_id(session: Session, tipo_id: int) -> TipoEquipamento:
    """Busca por id, inclusive inativos. Levanta exceção de domínio se não achar."""
    tipo = session.get(TipoEquipamento, tipo_id)
    if tipo is None:
        raise TipoEquipamentoNaoEncontrado(tipo_id)
    return tipo


def listar(
    session: Session,
    page: int = 1,
    size: int = TAMANHO_PAGINA_PADRAO,
    incluir_inativos: bool = False,
) -> PaginaTipos:
    """
    Lista paginado, ordenado por nome normalizado (ordem estável e
    previsível entre páginas — ordenar por `nome` deixaria "Ábaco" e
    "abaco" em posições dependentes de collation).

    Por padrão esconde os inativos: quem inativou um tipo não quer vê-lo
    de volta no seletor de cadastro.
    """
    page = max(1, page)
    size = max(1, min(size, TAMANHO_PAGINA_MAXIMO))

    filtros = [] if incluir_inativos else [TipoEquipamento.ativo.is_(True)]

    total = session.scalar(
        select(func.count()).select_from(TipoEquipamento).where(*filtros)
    )
    items = (
        session.scalars(
            select(TipoEquipamento)
            .where(*filtros)
            .order_by(TipoEquipamento.nome_normalizado)
            .offset((page - 1) * size)
            .limit(size)
        )
        .all()
    )
    return PaginaTipos(items=items, page=page, size=size, total=total or 0)


def atualizar(
    session: Session,
    tipo_id: int,
    nome: str | None = None,
    descricao: str | None = None,
    veio_descricao: bool = False,
) -> TipoEquipamento:
    """
    Atualização PARCIAL (PATCH).

    `veio_descricao` existe porque `descricao=None` é ambíguo num PATCH:
    pode significar "não mandei esse campo" ou "mandei explicitamente
    null para limpar a descrição". Sem essa distinção, qualquer PATCH que
    só troque o nome apagaria a descrição existente. Quem sabe se o campo
    veio no corpo da request é o router (via `model_fields_set` do
    Pydantic), então ele passa a resposta para cá.
    """
    tipo = buscar_por_id(session, tipo_id)

    if nome is not None:
        nome = nome.strip()
        tipo.nome = nome
        tipo.nome_normalizado = normalizar_nome(nome)

    if veio_descricao:
        tipo.descricao = descricao

    try:
        session.commit()
    except IntegrityError as erro:
        session.rollback()
        raise NomeDuplicado(nome or "") from erro
    session.refresh(tipo)
    return tipo


def contar_equipamentos(session: Session, tipo_id: int) -> int:
    """Conta equipamentos que referenciam o tipo para aplicar as restrições de inativação."""
    return (
        session.scalar(
            select(func.count())
            .select_from(Equipamento)
            .where(Equipamento.tipo_id == tipo_id)
        )
        or 0
    )


def inativar(session: Session, tipo_id: int) -> TipoEquipamento:
    """
    Baixa lógica. Nunca DELETE: `equipamentos.tipo_id` é FK obrigatória
    (ISS-008) e o histórico tem de continuar resolvendo o tipo.

    Bloqueia se ainda existir equipamento apontando para o tipo — é o
    critério de aceitação de integridade referencial da issue. Idempotente:
    inativar um tipo já inativo é no-op, não erro (um retry de request não
    pode virar 409).
    """
    tipo = buscar_por_id(session, tipo_id)
    if not tipo.ativo:
        return tipo

    total = contar_equipamentos(session, tipo_id)
    if total > 0:
        raise TipoEquipamentoEmUso(tipo_id, total)

    tipo.ativo = False
    session.commit()
    session.refresh(tipo)
    return tipo


def reativar(session: Session, tipo_id: int) -> TipoEquipamento:
    """Desfaz a baixa lógica. Idempotente, pelo mesmo motivo de `inativar`."""
    tipo = buscar_por_id(session, tipo_id)
    if tipo.ativo:
        return tipo

    tipo.ativo = True
    session.commit()
    session.refresh(tipo)
    return tipo
