"""Consulta segura da conectividade observada e agregação por portal (ISS-024)."""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from api.database import get_db
from api.permissoes import Permissao, exigir
from db.models import Antena, Leitor, MapeamentoAntenaPortal, Portal
from rfid_ingestion.reader_status import StatusPolicy, classify

Estado = Literal["online", "degradado", "offline", "nunca_conectado"]
router = APIRouter(tags=["status de hardware"],
                   dependencies=[Depends(exigir(Permissao.HARDWARE_CONSULTAR))])


class LeitorStatus(BaseModel):
    """Campos públicos explícitos; exclui rede e parâmetros de ingestão."""

    id: int
    reader_id: str
    modelo: str
    ativo: bool
    status: Estado
    motivo: str
    ultimo_contato_em: datetime | None
    ultimo_heartbeat_em: datetime | None
    origem_ultimo_contato: str | None
    segundos_sem_contato: float | None


class PortalStatus(BaseModel):
    """Agregação de leitores ativos e cobertura A/B da topologia vigente."""

    id: int
    nome: str
    ativo: bool
    status: Estado
    motivo: str
    leitores_ids: list[int]
    ultimo_contato_em: datetime | None
    lados_configurados: list[str]


class PainelStatus(BaseModel):
    """Leitores e portais classificados no mesmo instante, com limites explícitos."""

    consultado_em: datetime
    degradado_apos_segundos: float
    offline_apos_segundos: float
    leitores: list[LeitorStatus]
    portais: list[PortalStatus]


def status_context() -> tuple[datetime, StatusPolicy]:
    """Fornece relógio e limites compartilhados; substituível nos testes de fronteira."""
    return datetime.now(timezone.utc), StatusPolicy.from_env()


def _reader(reader: Leitor, now: datetime, policy: StatusPolicy) -> LeitorStatus:
    """Projeta o estado atual sem depender do último sweep do ingestor."""
    state, reason = classify(reader.ultimo_contato_em, reader.saude_reportada, now, policy)
    return LeitorStatus(id=reader.id, reader_id=reader.reader_id, modelo=reader.modelo,
                        ativo=reader.ativo, status=state, motivo=reason,
                        ultimo_contato_em=reader.ultimo_contato_em,
                        ultimo_heartbeat_em=reader.ultimo_heartbeat_em,
                        origem_ultimo_contato=reader.origem_ultimo_contato,
                        segundos_sem_contato=(max(0, (now - reader.ultimo_contato_em).total_seconds())
                                              if reader.ultimo_contato_em else None))


def aggregate(states: list[str], sides: set[str]) -> tuple[str, str]:
    """Agrega sem esconder falhas parciais; inativos são excluídos pelo chamador.

    Todos sem contato: nunca conectado. Todos silenciosos, mas algum contato
    prévio: offline. Todos online com lados A/B: online. Demais combinações:
    degradado. Portal sem leitor ativo permanece nunca conectado.
    """
    if not states:
        return "nunca_conectado", "sem_leitores_ativos"
    if all(state == "nunca_conectado" for state in states):
        return "nunca_conectado", "sem_contato_observado"
    if all(state in {"offline", "nunca_conectado"} for state in states):
        return "offline", "leitores_sem_contato"
    if sides != {"a", "b"}:
        return "degradado", "topologia_incompleta"
    if all(state == "online" for state in states):
        return "online", "todos_leitores_online"
    return "degradado", "falha_parcial_ou_degradacao"


def snapshot(db: Session, now: datetime, policy: StatusPolicy) -> PainelStatus:
    """Consulta topologia em lote, com ordenação estável por identidade."""
    readers = [_reader(reader, now, policy) for reader in
               db.scalars(select(Leitor).order_by(Leitor.reader_id, Leitor.id))]
    by_id = {reader.id: reader for reader in readers if reader.ativo}
    antennas = db.execute(select(Antena.portal_id, Antena.leitor_id)
                          .where(Antena.ativo.is_(True), Antena.portal_id.is_not(None))).all()
    mappings = db.execute(select(MapeamentoAntenaPortal.portal_id, MapeamentoAntenaPortal.lado)
                          .join(Antena, Antena.id == MapeamentoAntenaPortal.antena_id)
                          .where(Antena.ativo.is_(True), Antena.leitor_id.in_(list(by_id)),
                                 MapeamentoAntenaPortal.inicio <= now,
                                 or_(MapeamentoAntenaPortal.fim.is_(None),
                                     MapeamentoAntenaPortal.fim > now))).all()
    portals = []
    for portal in db.scalars(select(Portal).order_by(Portal.nome, Portal.id)):
        ids = sorted({reader_id for portal_id, reader_id in antennas
                      if portal_id == portal.id and reader_id in by_id})
        sides = {side for portal_id, side in mappings if portal_id == portal.id}
        state, reason = aggregate([by_id[reader_id].status for reader_id in ids], sides)
        seen = [by_id[reader_id].ultimo_contato_em for reader_id in ids
                if by_id[reader_id].ultimo_contato_em is not None]
        portals.append(PortalStatus(id=portal.id, nome=portal.nome, ativo=portal.ativo,
                                   status=state, motivo=reason, leitores_ids=ids,
                                   ultimo_contato_em=max(seen) if seen else None,
                                   lados_configurados=sorted(sides)))
    return PainelStatus(consultado_em=now, degradado_apos_segundos=policy.degraded_after,
                        offline_apos_segundos=policy.offline_after, leitores=readers, portais=portals)


@router.get("/leitores/status", response_model=PainelStatus,
            summary="Status de leitores e portais no mesmo instante")
def painel(db: Session = Depends(get_db),
           context: tuple[datetime, StatusPolicy] = Depends(status_context)) -> PainelStatus:
    """Retorna snapshot protegido por hardware:consultar, sem alterar dados no GET."""
    return snapshot(db, *context)


@router.get("/portais/status", response_model=list[PortalStatus],
            summary="Status agregado dos portais")
def portais(db: Session = Depends(get_db),
            context: tuple[datetime, StatusPolicy] = Depends(status_context)) -> list[PortalStatus]:
    """Expõe o agregado usado no painel, respeitando leitores e antenas ativos."""
    return snapshot(db, *context).portais
