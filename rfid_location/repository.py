"""Consultas da projeção. A decisão de recência ocorre somente após lock."""

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import aliased

from db.models import Equipamento, HistoricoMovimentacao, Passagem


def lock_equipment(connection: Connection, equipment_id: int):
    return connection.execute(
        select(
            Equipamento.id, Equipamento.ultima_zona_id,
            Equipamento.ultima_deteccao_em, Equipamento.ultima_passagem_id,
            Equipamento.ultima_movimentacao_id,
        ).where(Equipamento.id == equipment_id).with_for_update(
            of=Equipamento, key_share=True
        )
    ).one_or_none()


def update_location(
    connection: Connection, equipment_id: int, *, zone_id: int,
    movement_at, passage_id: int | None, movement_id: int,
) -> None:
    connection.execute(
        update(Equipamento).where(Equipamento.id == equipment_id).values(
            ultima_zona_id=zone_id, ultima_deteccao_em=movement_at,
            ultima_passagem_id=passage_id, ultima_movimentacao_id=movement_id,
        )
    )


def pending_ids(engine: Engine, *, limit: int = 100, after_id: int = 0) -> tuple[int, ...]:
    if limit < 1:
        raise ValueError("limit deve ser positivo")
    movement = aliased(HistoricoMovimentacao)
    query = (
        select(Passagem.id)
        .outerjoin(movement, and_(
            movement.passagem_id == Passagem.id,
            movement.origem_registro == "passagem_automatica",
        ))
        .outerjoin(Equipamento, Equipamento.id == movement.equipamento_id)
        .where(
            Passagem.direcao_status == "confirmed", Passagem.id > after_id,
            or_(
                movement.id.is_(None),
                Equipamento.ultima_deteccao_em.is_(None),
                movement.movimentada_em > Equipamento.ultima_deteccao_em,
            ),
        )
        .order_by(Passagem.id).limit(limit)
    )
    with engine.connect() as connection:
        return tuple(connection.scalars(query))
