"""Consultas de leitura limitadas para o painel operacional."""

from datetime import datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, aliased

from db.models import Equipamento, HistoricoMovimentacao, Zona


def resumo(db: Session, *, now: datetime, threshold: timedelta) -> dict[str, int]:
    cutoff = now - threshold
    detected = Equipamento.ultima_deteccao_em.is_not(None)
    row = db.execute(select(
        func.count(Equipamento.id).label("registered"),
        func.count(case((~detected, 1))).label("nunca_detectado"),
        func.count(case((detected & (Equipamento.status == "inativo"), 1))).label("fora_de_servico"),
        func.count(case((detected & (Equipamento.status == "ativo")
                         & (Equipamento.ultima_deteccao_em < cutoff), 1))).label("atencao"),
        func.count(case((detected & (Equipamento.status == "ativo")
                         & (Equipamento.ultima_deteccao_em >= cutoff), 1))).label("disponivel"),
    )).one()
    return dict(row._mapping)


def atividade_recente(db: Session, *, limit: int) -> list[dict]:
    origem = aliased(Zona)
    destino = aliased(Zona)
    rows = db.execute(
        select(HistoricoMovimentacao.id, Equipamento.id.label("equipamento_id"),
               Equipamento.nome.label("equipamento_nome"),
               origem.nome.label("zona_origem"), destino.nome.label("zona_destino"),
               HistoricoMovimentacao.movimentada_em,
               HistoricoMovimentacao.origem_registro)
        .join(Equipamento, Equipamento.id == HistoricoMovimentacao.equipamento_id)
        .outerjoin(origem, origem.id == HistoricoMovimentacao.zona_origem_id)
        .join(destino, destino.id == HistoricoMovimentacao.zona_destino_id)
        .where(HistoricoMovimentacao.movimentada_em.is_not(None))
        .order_by(HistoricoMovimentacao.movimentada_em.desc(),
                  HistoricoMovimentacao.id.desc())
        .limit(limit)
    ).mappings().all()
    return [dict(row) for row in rows]
