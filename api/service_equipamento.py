"""
Camada de serviço do CRUD de equipamentos (ISS-008).

Mesmo padrão de `api/service_tipos_equipamento.py`: roda contra uma
`Session` recebida por parâmetro, sem dependência de HTTP, e levanta
exceções de DOMÍNIO — nunca `HTTPException`. Mapear domínio para HTTP é
responsabilidade do router (`api/router_equipamento.py`).

Depende da ISS-009 (`api.service_tipos_equipamento`) para validar que
`tipo_id` aponta para um tipo que existe e está ativo.
"""

import math
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from api.normalizacao import normalizar_nome
from db.models import Equipamento, TipoEquipamento

TAMANHO_PAGINA_PADRAO = 20
TAMANHO_PAGINA_MAXIMO = 100

STATUS_ATIVO = "ativo"
STATUS_INATIVO = "inativo"


class ErroEquipamento(Exception):
    """Base das exceções de domínio deste serviço."""


class EquipamentoNaoEncontrado(ErroEquipamento):
    def __init__(self, equipamento_id: int) -> None:
        self.equipamento_id = equipamento_id
        super().__init__(f"Equipamento {equipamento_id} não encontrado.")


class EquipamentoNaoEncontradoPorIdentificador(EquipamentoNaoEncontrado):
    def __init__(self, identificador_interno: str) -> None:
        self.identificador_interno = identificador_interno
        self.identificador_normalizado = normalizar_nome(identificador_interno)
        self.equipamento_id = None
        ErroEquipamento.__init__(
            self,
            f"Equipamento com identificador interno {identificador_interno!r} não encontrado.",
        )


class IdentificadorDuplicado(ErroEquipamento):
    def __init__(self, identificador_interno: str) -> None:
        self.identificador_interno = identificador_interno
        self.identificador_normalizado = normalizar_nome(identificador_interno)
        super().__init__(
            f"Já existe um equipamento com o identificador interno "
            f"{identificador_interno!r} (normalizado: {self.identificador_normalizado!r})."
        )


class TipoEquipamentoInvalido(ErroEquipamento):
    """
    `tipo_id` não aponta para um tipo utilizável: ou não existe, ou existe
    mas está inativo. As duas causas são distinguidas só para a mensagem
    — o efeito no chamador (422) é o mesmo nos dois casos.
    """

    def __init__(self, tipo_id: int, motivo: str) -> None:
        self.tipo_id = tipo_id
        self.motivo = motivo
        super().__init__(f"tipo_id {tipo_id} inválido: {motivo}.")


class PaginaEquipamentos:
    """Resultado paginado de `listar`."""

    def __init__(
        self,
        items: Sequence[Equipamento],
        page: int,
        size: int,
        total: int,
    ) -> None:
        self.items = list(items)
        self.page = page
        self.size = size
        self.total = total
        self.pages = math.ceil(total / size) if size else 0


def _validar_tipo_ativo(session: Session, tipo_id: int) -> TipoEquipamento:
    """
    Levanta `TipoEquipamentoInvalido` se `tipo_id` não existir ou não
    estiver ativo. Usada tanto em `criar` quanto em `atualizar` (quando o
    PATCH troca o tipo).
    """
    tipo = session.get(TipoEquipamento, tipo_id)
    if tipo is None:
        raise TipoEquipamentoInvalido(tipo_id, "não existe")
    if not tipo.ativo:
        raise TipoEquipamentoInvalido(tipo_id, "está inativo")
    return tipo


def criar(
    session: Session,
    nome: str,
    tipo_id: int,
    identificador_interno: str,
    descricao: str | None = None,
) -> Equipamento:
    """
    Cadastra um equipamento novo.

    A validação de `tipo_id` é um SELECT explícito ANTES do insert (ao
    contrário da duplicidade de identificador, que é delegada ao UNIQUE do
    banco): não existe FK que garanta "ativo=true" a nível de banco, então
    a aplicação precisa checar. Uma corrida onde o tipo é inativado entre
    o SELECT e o INSERT é uma janela aceita para o MVP — a mesma
    observação já vale para o restante do cadastro deste projeto.
    """
    _validar_tipo_ativo(session, tipo_id)

    nome = nome.strip()
    identificador_interno = identificador_interno.strip()
    equipamento = Equipamento(
        nome=nome,
        tipo_id=tipo_id,
        identificador_interno=identificador_interno,
        identificador_interno_normalizado=normalizar_nome(identificador_interno),
        descricao=descricao,
    )
    session.add(equipamento)
    try:
        session.commit()
    except IntegrityError as erro:
        session.rollback()
        raise IdentificadorDuplicado(identificador_interno) from erro
    session.refresh(equipamento)
    # Carrega `tipo` para a resposta poder incluir `tipo_nome` sem query
    # extra — o objeto acabou de ser validado, então já sabemos que existe.
    session.refresh(equipamento, attribute_names=["tipo"])
    return equipamento


def buscar_por_id(session: Session, equipamento_id: int) -> Equipamento:
    """
    Busca por id, inclusive inativos, com `tipo` carregado via
    `joinedload` — a resposta da API precisa do nome do tipo, e um
    `lazy load` implícito por request seria uma query extra por chamada
    (N+1 na listagem).
    """
    equipamento = session.scalar(
        select(Equipamento)
        .options(joinedload(Equipamento.tipo))
        .where(Equipamento.id == equipamento_id)
    )
    if equipamento is None:
        raise EquipamentoNaoEncontrado(equipamento_id)
    return equipamento


def buscar_por_identificador(session: Session, identificador_interno: str) -> Equipamento:
    """
    Busca por identificador interno (normalizado), inclusive inativos,
    com `tipo` carregado via `joinedload` — mesmo padrão de `buscar_por_id`.
    """
    normalizado = normalizar_nome(identificador_interno)
    equipamento = session.scalar(
        select(Equipamento)
        .options(joinedload(Equipamento.tipo))
        .where(Equipamento.identificador_interno_normalizado == normalizado)
    )
    if equipamento is None:
        raise EquipamentoNaoEncontradoPorIdentificador(identificador_interno)
    return equipamento


def listar(
    session: Session,
    page: int = 1,
    size: int = TAMANHO_PAGINA_PADRAO,
    incluir_inativos: bool = False,
) -> PaginaEquipamentos:
    """
    Lista paginada, com `tipo` carregado via `joinedload` (mesma razão de
    `buscar_por_id`: sem isso, montar `tipo_nome` de cada item da página
    seria uma query por linha).

    Por padrão esconde os inativos, mesmo critério de `tipos_equipamento`.
    """
    page = max(1, page)
    size = max(1, min(size, TAMANHO_PAGINA_MAXIMO))

    filtros = [] if incluir_inativos else [Equipamento.status == STATUS_ATIVO]

    total = session.scalar(select(func.count()).select_from(Equipamento).where(*filtros))
    items = (
        session.scalars(
            select(Equipamento)
            .options(joinedload(Equipamento.tipo))
            .where(*filtros)
            .order_by(Equipamento.identificador_interno_normalizado)
            .offset((page - 1) * size)
            .limit(size)
        )
        .unique()
        .all()
    )
    return PaginaEquipamentos(items=items, page=page, size=size, total=total or 0)


def atualizar(
    session: Session,
    equipamento_id: int,
    nome: str | None = None,
    tipo_id: int | None = None,
    descricao: str | None = None,
    descricao_informada: bool = False,
) -> Equipamento:
    """
    Atualização PARCIAL (PATCH). SEM `identificador_interno`: é imutável,
    o schema de entrada (`EquipamentoAtualizar`) nem aceita o campo.

    Se `tipo_id` vier, valida que o tipo novo existe e está ativo ANTES de
    trocar — mesma regra de `criar`.

    `descricao_informada` resolve a mesma ambiguidade de
    `atualizar` em `service_tipos_equipamento`: `descricao=None` pode
    significar "não veio no payload" ou "veio null para limpar o campo".
    """
    equipamento = buscar_por_id(session, equipamento_id)

    if tipo_id is not None:
        _validar_tipo_ativo(session, tipo_id)
        equipamento.tipo_id = tipo_id

    if nome is not None:
        equipamento.nome = nome.strip()

    if descricao_informada:
        equipamento.descricao = descricao

    # Sem try/except de IntegrityError aqui, ao contrário de `criar`:
    # nada que este método muda tem UNIQUE (identificador_interno é
    # imutável e nem está entre os parâmetros) e `tipo_id` já foi validado
    # acima, então não há gatilho de violação de constraint neste ponto.
    session.commit()
    session.refresh(equipamento)
    session.refresh(equipamento, attribute_names=["tipo"])
    return equipamento


def inativar(session: Session, equipamento_id: int) -> Equipamento:
    """
    Baixa lógica (`status = 'inativo'`). Nunca DELETE.

    Ao contrário de `TipoEquipamento.inativar`, não há bloqueio de "em
    uso": inativar um equipamento não quebra integridade referencial de
    nada — é só um marcador de que ele saiu de circulação. Idempotente:
    inativar duas vezes não é erro.
    """
    equipamento = buscar_por_id(session, equipamento_id)
    if equipamento.status == STATUS_INATIVO:
        return equipamento

    equipamento.status = STATUS_INATIVO
    session.commit()
    session.refresh(equipamento)
    session.refresh(equipamento, attribute_names=["tipo"])
    return equipamento


def reativar(session: Session, equipamento_id: int) -> Equipamento:
    """Desfaz a baixa lógica. Idempotente, pelo mesmo motivo de `inativar`."""
    equipamento = buscar_por_id(session, equipamento_id)
    if equipamento.status == STATUS_ATIVO:
        return equipamento

    equipamento.status = STATUS_ATIVO
    session.commit()
    session.refresh(equipamento)
    session.refresh(equipamento, attribute_names=["tipo"])
    return equipamento
