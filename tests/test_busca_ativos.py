"""Matriz ISS-019 contra PostgreSQL local descartável e contrato HTTP."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.database import get_db
from api.main import app
from api.router_equipamento import get_recency_context
from api.service_busca_ativos import buscar
from db.models import (
    Andar,
    AssociacaoTagEquipamento,
    Equipamento,
    Setor,
    Tag,
    TipoEquipamento,
    Zona,
)

NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
THRESHOLD = timedelta(minutes=30)


@pytest.fixture
def catalog(db):
    maca = TipoEquipamento(nome="Maca", nome_normalizado="maca")
    bomba = TipoEquipamento(nome="Bomba", nome_normalizado="bomba")
    floor = Andar(nome="Piso teste", nome_normalizado="piso teste")
    db.add_all([maca, bomba, floor])
    db.flush()
    sector = Setor(andar_id=floor.id, nome="Setor teste", nome_normalizado="setor teste")
    db.add(sector)
    db.flush()
    zone_a = Zona(setor_id=sector.id, nome="Zona A", nome_normalizado="zona a",
                  referencia_planta="zona-1")
    zone_b = Zona(setor_id=sector.id, nome="Zona B", nome_normalizado="zona b")
    db.add_all([zone_a, zone_b])
    db.flush()
    rows = [
        Equipamento(nome="Maca A", tipo_id=maca.id, identificador_interno="PAT-1",
                    identificador_interno_normalizado="pat1", ultima_zona_id=zone_a.id,
                    ultima_deteccao_em=NOW - timedelta(minutes=5)),
        Equipamento(nome="Maca B", tipo_id=maca.id, identificador_interno="PAT-2",
                    identificador_interno_normalizado="pat2", ultima_zona_id=zone_b.id,
                    ultima_deteccao_em=NOW - timedelta(hours=2)),
        Equipamento(nome="Bomba C", tipo_id=bomba.id, identificador_interno="PAT-3",
                    identificador_interno_normalizado="pat3"),
        Equipamento(nome="Maca D", tipo_id=maca.id, identificador_interno="PAT-4",
                    identificador_interno_normalizado="pat4", ultima_zona_id=zone_a.id,
                    ultima_deteccao_em=NOW - timedelta(minutes=4), status="inativo"),
    ]
    db.add_all(rows)
    db.flush()
    tag = Tag(epc="E2000017221101441890A001")
    db.add(tag)
    db.flush()
    db.add(AssociacaoTagEquipamento(tag_id=tag.id, equipamento_id=rows[0].id))
    db.flush()
    return {"maca": maca.id, "bomba": bomba.id, "a": zone_a.id, "b": zone_b.id,
            "ids": [row.id for row in rows]}


def search(db, **filters):
    return buscar(db, now=NOW, threshold=THRESHOLD, **filters)


def test_filtros_isolados_e_cumulativos(db, catalog):
    ids = catalog["ids"]
    assert [x.id for x in search(db, q="maca").items] == [ids[0], ids[1], ids[3]]
    assert [x.id for x in search(db, q="PAT-3").items] == [ids[2]]
    assert search(db, q="%").items == []
    assert search(db, q="_").items == []
    assert [x.id for x in search(db, tipo=catalog["bomba"]).items] == [ids[2]]
    assert [x.id for x in search(db, zona=catalog["b"]).items] == [ids[1]]
    assert [x.id for x in search(db, status="atencao").items] == [ids[1]]
    assert [x.id for x in search(db, epc="E2000017221101441890A001").items] == [ids[0]]
    assert [x.id for x in search(db, tipo=catalog["maca"], zona=catalog["a"],
                                 status="disponivel").items] == [ids[0]]
    assert search(db, epc="FFFFFFFFFFFFFFFFFFFFFFFF").total == 0
    assert search(db, zona=catalog["b"], epc="E2000017221101441890A001").items == []
    assert search(db, status="offline").items == []


def test_paginacao_estados_e_epc_atual(db, catalog):
    first = search(db, page_size=2)
    second = search(db, page=2, page_size=2)
    assert first.total == second.total == 4
    assert len(first.items) == len(second.items) == 2
    assert {x.id for x in first.items}.isdisjoint({x.id for x in second.items})
    assert search(db, page=3, page_size=2).items == []
    assert len(search(db, page_size=100).items) == 4
    never = search(db, status="nunca_detectado").items[0]
    assert never.ultima_zona is None
    assert never.ultima_deteccao_em is None
    assert never.localizacao_desatualizada is None
    outdated = search(db, status="atencao").items[0]
    assert outdated.localizacao_desatualizada is True
    assert outdated.ultima_zona.andar == "Piso teste"
    assert outdated.ultima_zona.setor == "Setor teste"
    assert outdated.ultima_zona.caminho == "Piso teste → Setor teste → Zona B"
    assert outdated.ultima_deteccao_em.utcoffset() == timedelta(0)
    assert search(db, status="fora_de_servico").items[0].id == catalog["ids"][3]
    assert search(db, sort="-nome").items[0].nome == "Maca D"


def test_validacao_http(db, catalog):
    db.execute(text("SET LOCAL TIME ZONE 'America/Maceio'"))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_recency_context] = lambda: (NOW, THRESHOLD)
    try:
        with TestClient(app) as client:
            for query in ("page=0", "page_size=101", "page_size=0", "tipo=-1", "zona=x",
                          "status=invalido", "sort=aleatorio", "q=%20%20", "epc=XYZ"):
                assert client.get(f"/api/ativos?{query}").status_code == 422
            assert client.get("/api/ativos?epc=FFFFFFFFFFFFFFFFFFFFFFFF").json() == {
                "items": [], "total": 0, "page": 1, "page_size": 20,
            }
            result = client.get("/api/ativos?status=nunca_detectado")
            assert result.status_code == 200
            assert result.json()["items"][0]["ultima_zona"] is None
            detected = client.get("/api/ativos?zona=" + str(catalog["a"]))
            assert detected.status_code == 200
            assert detected.json()["items"][0]["ultima_zona"]["caminho"] == (
                "Piso teste → Setor teste → Zona A"
            )
            assert detected.json()["items"][0]["ultima_deteccao_em"].endswith("Z")
    finally:
        app.dependency_overrides.clear()
