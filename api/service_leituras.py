"""Presença por leitura bruta: contagens recentes por EPC e antena.

Complementa a última zona confirmada (ISS-017) sem substituí-la: uma tag lida
em uma antena está *presente* no alcance dessa antena, mas a zona do
equipamento só muda por passagem confirmada. Antenas de um mesmo portal podem
ler a mesma tag ao mesmo tempo, então a zona da antena aqui é indicativa.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import and_, func, select, text, true
from sqlalchemy.orm import Session

from api.equipamento_visivel import nao_arquivado
from api.timestamps import em_utc
from db.models import (
    Antena,
    AssociacaoTagEquipamento,
    Equipamento,
    Leitor,
    LeituraBruta,
    Tag,
    Zona,
)

LIMITE_NAO_CADASTRADAS = 200


def _antenas(db: Session, ids: Iterable[int]) -> dict[int, dict]:
    """Lista antenas e zonas para identificar a origem das leituras na resposta."""
    ids = set(ids)
    if not ids:
        return {}
    linhas = db.execute(
        select(Antena.id, Antena.porta_numero, Leitor.reader_id, Zona.nome)
        .join(Leitor, Leitor.id == Antena.leitor_id)
        .outerjoin(Zona, Zona.id == Antena.zona_associada_id)
        .where(Antena.id.in_(ids))
    ).all()
    return {
        linha.id: {"antena_id": linha.id, "leitor": linha.reader_id,
                   "porta": linha.porta_numero, "zona": linha.nome}
        for linha in linhas
    }


def ultimas_leituras(db: Session, epcs: Iterable[str]) -> dict[str, dict]:
    """Última leitura de cada EPC, uma busca indexada por EPC (epc, lido_em)."""
    epcs = sorted(set(epcs))
    if not epcs:
        return {}
    linhas = db.execute(text("""
        SELECT e.epc, u.lido_em, u.antena_id
          FROM unnest(CAST(:epcs AS varchar[])) AS e(epc)
          CROSS JOIN LATERAL (
                SELECT l.lido_em, l.antena_id FROM leituras_brutas l
                 WHERE l.epc = e.epc ORDER BY l.lido_em DESC LIMIT 1) u
    """), {"epcs": epcs}).all()
    antenas = _antenas(db, (linha.antena_id for linha in linhas))
    return {
        linha.epc: {"em": em_utc(linha.lido_em), **antenas.get(linha.antena_id, {})}
        for linha in linhas
    }


def resumo(db: Session, *, now: datetime, janela: timedelta,
           somente_cadastradas: bool = False, somente_ativos: bool = False) -> dict:
    """Agrega leituras da janela por tag e antena e associa apenas o vínculo ativo do equipamento."""
    corte = now - janela
    cadastradas = {
        linha.epc: {
            "id": linha.id, "nome": linha.nome,
            "identificador_interno": linha.identificador_interno,
            "ultima_zona": linha.zona,
            "ultima_zona_em": em_utc(linha.ultima_deteccao_em),
        }
        for linha in db.execute(
            select(Tag.epc, Equipamento.id, Equipamento.nome,
                   Equipamento.identificador_interno, Equipamento.ultima_deteccao_em,
                   Zona.nome.label("zona"))
            .join(AssociacaoTagEquipamento, and_(
                AssociacaoTagEquipamento.tag_id == Tag.id,
                AssociacaoTagEquipamento.fim.is_(None)))
            .join(Equipamento, Equipamento.id == AssociacaoTagEquipamento.equipamento_id)
            .outerjoin(Zona, Zona.id == Equipamento.ultima_zona_id)
            .where(nao_arquivado() if somente_ativos else true())
        ).all()
    }

    agregado = (
        select(LeituraBruta.epc, LeituraBruta.antena_id,
               func.count().label("leituras"), func.max(LeituraBruta.lido_em).label("ultima"))
        .where(LeituraBruta.lido_em >= corte)
        .group_by(LeituraBruta.epc, LeituraBruta.antena_id)
    )
    if somente_cadastradas:
        agregado = agregado.where(LeituraBruta.epc.in_(list(cadastradas) or [""]))
    # Fora de serviço continua com etiqueta e continua sendo lido: não é escondido.
    # Arquivados não têm etiqueta vinculada, então suas leituras já não se ligam a eles.
    por_epc: dict[str, list] = {}
    for linha in db.execute(agregado).all():
        por_epc.setdefault(linha.epc, []).append(linha)

    sem_leitura = [epc for epc in cadastradas if epc not in por_epc]
    anteriores = ultimas_leituras(db, sem_leitura)
    antenas = _antenas(db, (linha.antena_id for linhas in por_epc.values() for linha in linhas))

    items = []
    for epc, linhas in por_epc.items():
        mais_recente = max(linhas, key=lambda linha: linha.ultima)
        items.append({
            "epc": epc,
            "cadastrada": epc in cadastradas,
            "equipamento": cadastradas.get(epc),
            "leituras": sum(linha.leituras for linha in linhas),
            "leituras_por_antena": sorted(
                ({"antena_id": linha.antena_id, "leituras": linha.leituras} for linha in linhas),
                key=lambda item: item["antena_id"]),
            "ultima_leitura": {"em": em_utc(mais_recente.ultima),
                               **antenas.get(mais_recente.antena_id, {})},
        })
    for epc in sem_leitura:
        items.append({
            "epc": epc, "cadastrada": True, "equipamento": cadastradas[epc],
            "leituras": 0, "leituras_por_antena": [],
            "ultima_leitura": anteriores.get(epc),
        })
    items.sort(key=lambda item: (not item["cadastrada"], -item["leituras"], item["epc"]))
    nao_cadastradas = sum(1 for item in items if not item["cadastrada"])
    totais = {
        "total_leituras": sum(item["leituras"] for item in items),
        "tags_detectadas": sum(1 for item in items if item["leituras"]),
        "cadastradas_detectadas": sum(1 for item in items
                                      if item["cadastrada"] and item["leituras"]),
        "cadastradas_sem_leitura": len(sem_leitura),
        "nao_cadastradas": nao_cadastradas,
    }
    if nao_cadastradas > LIMITE_NAO_CADASTRADAS:
        items = [item for item in items if item["cadastrada"]] + [
            item for item in items if not item["cadastrada"]][:LIMITE_NAO_CADASTRADAS]
    return {
        "janela_segundos": int(janela.total_seconds()),
        "gerado_em": em_utc(now),
        **totais,
        "antenas": sorted(antenas.values(), key=lambda a: (a["leitor"], a["porta"])),
        "items": items,
    }
