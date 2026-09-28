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
    HistoricoMovimentacao,
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
        Equipamento(nome="Bomba E", tipo_id=bomba.id, identificador_interno="PAT-5",
                    identificador_interno_normalizado="pat5", ultima_zona_id=zone_a.id,
                    ultima_deteccao_em=NOW - timedelta(minutes=3)),
        Equipamento(nome="Bomba F", tipo_id=bomba.id, identificador_interno="PAT-6",
                    identificador_interno_normalizado="pat6", ultima_zona_id=zone_b.id,
                    ultima_deteccao_em=NOW - timedelta(minutes=2)),
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


def test_dashboard_resumo_e_atividade_limitada(db, catalog):
    db.add_all([
        HistoricoMovimentacao(equipamento_id=catalog["ids"][0],
                              zona_destino_id=catalog["a"],
                              origem_registro="correcao_manual", justificativa="Teste",
                              movimentada_em=NOW - timedelta(minutes=2)),
        HistoricoMovimentacao(equipamento_id=catalog["ids"][1],
                              zona_destino_id=catalog["b"],
                              origem_registro="correcao_manual", justificativa="Teste",
                              movimentada_em=NOW - timedelta(minutes=1)),
    ])
    db.flush()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_recency_context] = lambda: (NOW, THRESHOLD)
    try:
        with TestClient(app) as client:
            summary = client.get("/api/dashboard/resumo")
            assert summary.status_code == 200
            assert summary.json() == {"registered": 6, "disponivel": 3, "atencao": 1,
                                      "fora_de_servico": 1, "nunca_detectado": 1}
            activity = client.get("/api/dashboard/atividade?limit=1")
            assert activity.status_code == 200
            assert len(activity.json()["items"]) == 1
            assert activity.json()["items"][0]["equipamento_nome"] == "Maca B"
            assert client.get("/api/dashboard/atividade?limit=21").status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_filtros_isolados_e_cumulativos(db, catalog):
    ids = catalog["ids"]
    assert [x.id for x in search(db, q="maca").items] == [ids[0], ids[1], ids[3]]
    assert [x.id for x in search(db, q="PAT-3").items] == [ids[2]]
    assert search(db, q="%").items == []
    assert search(db, q="_").items == []
    assert [x.id for x in search(db, tipo=catalog["bomba"]).items] == [ids[2], ids[4], ids[5]]
    assert [x.id for x in search(db, zona=catalog["b"]).items] == [ids[5], ids[1]]
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
    assert first.total == second.total == 6
    assert len(first.items) == len(second.items) == 2
    assert {x.id for x in first.items}.isdisjoint({x.id for x in second.items})
    assert search(db, page=4, page_size=2).items == []
    assert len(search(db, page_size=100).items) == 6
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


def test_zonas_retornam_todos_e_somente_seus_ativos(db, catalog):
    ids = catalog["ids"]
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_recency_context] = lambda: (NOW, THRESHOLD)
    try:
        with TestClient(app) as client:
            for zone, expected in (("a", {ids[0], ids[3], ids[4]}),
                                   ("b", {ids[1], ids[5]})):
                response = client.get("/api/ativos", params={"zona": catalog[zone]})
                assert response.status_code == 200
                page = response.json()
                returned = [item["id"] for item in page["items"]]
                assert page["total"] == len(expected)
                assert (page["page"], page["page_size"]) == (1, 20)
                assert len(returned) == len(set(returned))
                assert set(returned) == expected
                assert all(item["ultima_zona"]["id"] == catalog[zone]
                           for item in page["items"])
                assert all(item["tipo"] and item["identificador_interno"]
                           and item["ultima_deteccao_em"] for item in page["items"])

            stale = client.get("/api/ativos", params={"zona": catalog["b"]}).json()["items"]
            assert {item["id"]: (item["status"], item["localizacao_desatualizada"])
                    for item in stale} == {
                        ids[1]: ("atencao", True), ids[5]: ("disponivel", False),
                    }
            assert client.get("/api/ativos", params={"zona": catalog["b"],
                                                     "status": "atencao"}).json()["total"] == 1
            recent_only = client.get("/api/ativos", params={
                "zona": catalog["b"], "status": "disponivel",
            }).json()
            assert {item["id"] for item in recent_only["items"]} == {ids[5]}

            for zone in (catalog["a"], catalog["b"]):
                assert ids[2] not in {item["id"] for item in client.get(
                    "/api/ativos", params={"zona": zone}).json()["items"]}
            assert client.get("/api/ativos?zona=0").status_code == 422
            assert client.get("/api/ativos?zona=invalida").status_code == 422
            assert client.get("/api/ativos?zona=999999").json() == {
                "items": [], "total": 0, "page": 1, "page_size": 20,
            }
            inactive_zone = Zona(
                setor_id=db.get(Zona, catalog["a"]).setor_id,
                nome="Zona inativa", nome_normalizado="zona inativa", ativo=False,
            )
            db.add(inactive_zone)
            db.flush()
            assert client.get("/api/ativos", params={"zona": inactive_zone.id}).json() == {
                "items": [], "total": 0, "page": 1, "page_size": 20,
            }
    finally:
        app.dependency_overrides.clear()


def test_paginacao_e_mudanca_da_ultima_zona_no_http(db, catalog):
    ids = catalog["ids"]
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_recency_context] = lambda: (NOW, THRESHOLD)
    try:
        with TestClient(app) as client:
            pages = [client.get("/api/ativos", params={"zona": catalog["a"],
                                                       "page": number, "page_size": 2}).json()
                     for number in (1, 2, 3)]
            assert [page["total"] for page in pages] == [3, 3, 3]
            assert [(page["page"], page["page_size"]) for page in pages] == [
                (1, 2), (2, 2), (3, 2),
            ]
            assert [[item["id"] for item in page["items"]] for page in pages] == [
                [ids[4], ids[0]], [ids[3]], [],
            ]

            moved = db.get(Equipamento, ids[0])
            moved.ultima_zona_id = catalog["b"]
            moved.ultima_deteccao_em = NOW - timedelta(minutes=1)
            db.flush()
            zone_a = client.get("/api/ativos", params={"zona": catalog["a"]}).json()
            zone_b = client.get("/api/ativos", params={"zona": catalog["b"]}).json()
            assert {item["id"] for item in zone_a["items"]} == {ids[3], ids[4]}
            assert {item["id"] for item in zone_b["items"]} == {ids[0], ids[1], ids[5]}
            assert zone_a["total"] == 2
            assert zone_b["total"] == 3
            assert next(item for item in zone_b["items"] if item["id"] == ids[0])[
                "ultima_zona"]["id"] == catalog["b"]
    finally:
        app.dependency_overrides.clear()
