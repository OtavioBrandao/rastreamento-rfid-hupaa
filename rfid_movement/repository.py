"""Persistência append-only; cada operação participa da Connection recebida."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection
from sqlalchemy.orm import aliased

from db.models import (
    AssociacaoTagEquipamento,
    Equipamento,
    HistoricoMovimentacao,
    Passagem,
    Portal,
    Tag,
    Zona,
)

from .types import MovementEvent, MovementPage, MovementRecord


def load_passage(connection: Connection, passage_id: int):
    return connection.execute(select(Passagem.__table__).where(Passagem.id == passage_id)).mappings().one_or_none()


def resolve_equipment(connection: Connection, epc: str, at: datetime) -> tuple[int, ...]:
    return tuple(connection.scalars(
        select(AssociacaoTagEquipamento.equipamento_id)
        .join(Tag, Tag.id == AssociacaoTagEquipamento.tag_id)
        .where(
            Tag.epc == epc,
            AssociacaoTagEquipamento.inicio <= at,
            or_(AssociacaoTagEquipamento.fim.is_(None), AssociacaoTagEquipamento.fim > at),
        )
        .limit(2)
    ))


def append(connection: Connection, event: MovementEvent) -> tuple[int, bool]:
    values = vars(event)
    statement = insert(HistoricoMovimentacao).values(**values).returning(HistoricoMovimentacao.id)
    if event.origem_registro == "passagem_automatica":
        statement = statement.on_conflict_do_nothing(
            index_elements=[HistoricoMovimentacao.passagem_id],
            index_where=HistoricoMovimentacao.origem_registro == "passagem_automatica",
        )
    movement_id = connection.scalar(statement)
    if movement_id is not None:
        return movement_id, True
    existing = connection.scalar(
        select(HistoricoMovimentacao.id).where(
            HistoricoMovimentacao.passagem_id == event.passagem_id,
            HistoricoMovimentacao.origem_registro == "passagem_automatica",
        )
    )
    if existing is None:
        raise RuntimeError("conflito de histórico sem registro existente")
    return existing, False


def get_movement(connection: Connection, movement_id: int):
    return connection.execute(
        select(HistoricoMovimentacao.__table__).where(HistoricoMovimentacao.id == movement_id)
    ).mappings().one_or_none()


def get_automatic_for_passage(connection: Connection, passage_id: int):
    return connection.execute(
        select(HistoricoMovimentacao.id, HistoricoMovimentacao.equipamento_id)
        .where(HistoricoMovimentacao.passagem_id == passage_id,
               HistoricoMovimentacao.origem_registro == "passagem_automatica")
    ).one_or_none()


def equipment_exists(connection: Connection, equipment_id: int) -> bool:
    return connection.scalar(select(Equipamento.id).where(Equipamento.id == equipment_id)) is not None


def list_for_equipment(
    connection: Connection, equipment_id: int, *, page: int, size: int,
    inicio: datetime | None = None, fim: datetime | None = None,
) -> MovementPage:
    if page < 1 or not 1 <= size <= 100:
        raise ValueError("page e size inválidos")
    if inicio is not None and fim is not None and inicio >= fim:
        raise ValueError("inicio deve ser anterior a fim")
    origem = aliased(Zona)
    destino = aliased(Zona)
    filters = [HistoricoMovimentacao.equipamento_id == equipment_id]
    if inicio is not None:
        filters.append(HistoricoMovimentacao.movimentada_em >= inicio)
    if fim is not None:
        filters.append(HistoricoMovimentacao.movimentada_em < fim)
    total = connection.scalar(
        select(func.count()).select_from(HistoricoMovimentacao).where(and_(*filters))
    ) or 0
    rows = connection.execute(
        select(
            HistoricoMovimentacao.__table__,
            origem.nome.label("zona_origem"),
            destino.nome.label("zona_destino"),
            Portal.nome.label("portal"),
        )
        .outerjoin(origem, origem.id == HistoricoMovimentacao.zona_origem_id)
        .join(destino, destino.id == HistoricoMovimentacao.zona_destino_id)
        .outerjoin(Portal, Portal.id == HistoricoMovimentacao.portal_id)
        .where(and_(*filters))
        .order_by(HistoricoMovimentacao.movimentada_em.desc().nulls_last(),
                  HistoricoMovimentacao.id.desc())
        .offset((page - 1) * size).limit(size)
    ).mappings().all()
    items = tuple(MovementRecord(
        id=row.id,
        equipamento_id=row.equipamento_id,
        epc=row.epc,
        origem_registro=row.origem_registro,
        zona_origem_id=row.zona_origem_id,
        zona_origem=row.zona_origem,
        zona_destino_id=row.zona_destino_id,
        zona_destino=row.zona_destino,
        portal_id=row.portal_id,
        portal=row.portal,
        passagem_id=row.passagem_id,
        leitura_origem_id=row.leitura_origem_id,
        leitura_destino_id=row.leitura_destino_id,
        movimentada_em=row.movimentada_em,
        registrado_em=row.registrado_em,
        justificativa=row.justificativa,
        registro_anterior_id=row.registro_anterior_id,
        referencia=row.referencia,
    ) for row in rows)
    return MovementPage(items, page, size, total, (total + size - 1) // size)
