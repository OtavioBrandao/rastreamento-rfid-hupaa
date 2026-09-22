"""Ledger ISS-018 no PostgreSQL: tempo, transações, concorrência e consulta."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.database import get_db
from api.main import app
from db.models import (
    Andar,
    Antena,
    AssociacaoTagEquipamento,
    Equipamento,
    HistoricoMovimentacao,
    Leitor,
    LeituraBruta,
    Passagem,
    Portal,
    Setor,
    Tag,
    TipoEquipamento,
    Zona,
)
from rfid_movement.repository import list_for_equipment, resolve_equipment
from rfid_movement.service import append_automatic_movement, append_manual_correction

T = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)


@pytest.fixture
def setup(pg_engine):
    with pg_engine.begin() as c:
        floor = c.scalar(Andar.__table__.insert().values(
            nome="andar", nome_normalizado="andar").returning(Andar.id))
        sector = c.scalar(Setor.__table__.insert().values(
            andar_id=floor, nome="setor", nome_normalizado="setor").returning(Setor.id))
        zones = [c.scalar(Zona.__table__.insert().values(
            setor_id=sector, nome=f"zona {i}", nome_normalizado=f"zona {i}"
        ).returning(Zona.id)) for i in range(3)]
        portal = c.scalar(Portal.__table__.insert().values(
            nome="portal", zona_a_id=zones[0], zona_b_id=zones[1]
        ).returning(Portal.id))
        reader = c.scalar(Leitor.__table__.insert().values(
            reader_id="r1", identificador_serial="s1", fabricante="f", modelo="m"
        ).returning(Leitor.id))
        antennas = [c.scalar(Antena.__table__.insert().values(
            leitor_id=reader, porta_numero=i + 1, zona_associada_id=zones[i],
            funcao="indefinido"
        ).returning(Antena.id)) for i in range(2)]
        readings = [c.scalar(LeituraBruta.__table__.insert().values(
            event_id=f"e{i}", antena_id=antennas[i], epc="EPC-X",
            lido_em=T - timedelta(seconds=1 - i)
        ).returning(LeituraBruta.id)) for i in range(2)]
        passage = c.scalar(Passagem.__table__.insert().values(
            epc="EPC-X", portal_id=portal,
            antena_origem_id=antennas[0], antena_destino_id=antennas[1],
            leitura_origem_id=readings[0], leitura_destino_id=readings[1],
            detectada_em=T, direcao="a_para_b", direcao_status="confirmed",
            direcao_regra="temporal_side_order_v1",
            zona_origem_id=zones[0], zona_destino_id=zones[1],
        ).returning(Passagem.id))
        kind = c.scalar(TipoEquipamento.__table__.insert().values(
            nome="tipo", nome_normalizado="tipo").returning(TipoEquipamento.id))
        equipments = [c.scalar(Equipamento.__table__.insert().values(
            nome=f"equipamento {i}", tipo_id=kind, identificador_interno=f"EQ-{i}",
            identificador_interno_normalizado=f"eq-{i}"
        ).returning(Equipamento.id)) for i in range(2)]
        tag = c.scalar(Tag.__table__.insert().values(epc="EPC-X").returning(Tag.id))
        c.execute(AssociacaoTagEquipamento.__table__.insert().values(
            tag_id=tag, equipamento_id=equipments[0], inicio=T - timedelta(days=30),
            fim=T + timedelta(days=30),
        ))
        c.execute(AssociacaoTagEquipamento.__table__.insert().values(
            tag_id=tag, equipamento_id=equipments[1], inicio=T + timedelta(days=30),
        ))
    return {"passage": passage, "equipment_a": equipments[0], "equipment_b": equipments[1],
            "zones": zones, "portal": portal, "readings": readings, "tag": tag}


def test_historical_owner_and_iss016_contract(pg_engine, setup):
    with pg_engine.begin() as c:
        assert resolve_equipment(c, "EPC-X", T - timedelta(days=30)) == (setup["equipment_a"],)
        assert resolve_equipment(c, "EPC-X", T + timedelta(days=30)) == (setup["equipment_b"],)
        result = append_automatic_movement(c, setup["passage"])
        assert result.status == "recorded"
    with pg_engine.connect() as c:
        row = c.execute(select(HistoricoMovimentacao.__table__)).mappings().one()
        assert row["equipamento_id"] == setup["equipment_a"]
        assert row["epc"] == "EPC-X"
        assert row["portal_id"] == setup["portal"]
        assert (row["zona_origem_id"], row["zona_destino_id"]) == tuple(setup["zones"][:2])
        assert (row["leitura_origem_id"], row["leitura_destino_id"]) == tuple(setup["readings"])
        assert row["passagem_id"] == setup["passage"]
        assert row["movimentada_em"] == T
        assert row["registrado_em"] >= T
        assert row["origem_registro"] == "passagem_automatica"
        assert c.execute(select(
            Equipamento.ultima_zona_id, Equipamento.ultima_deteccao_em,
            Equipamento.ultima_passagem_id
        ).where(Equipamento.id == setup["equipment_a"])).one() == (None, None, None)
    with pg_engine.begin() as c:
        assert append_automatic_movement(c, setup["passage"]).status == "duplicate"
        assert c.scalar(select(func.count()).select_from(HistoricoMovimentacao)) == 1


def test_rollback_and_concurrent_replay(pg_engine, setup):
    with pytest.raises(RuntimeError), pg_engine.begin() as c:
        assert append_automatic_movement(c, setup["passage"]).status == "recorded"
        raise RuntimeError("rollback")
    with pg_engine.connect() as c:
        assert c.scalar(select(func.count()).select_from(HistoricoMovimentacao)) == 0

    def worker(_):
        with pg_engine.begin() as c:
            return append_automatic_movement(c, setup["passage"]).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(worker, range(2))) == ["duplicate", "recorded"]
    with pg_engine.connect() as c:
        assert c.scalar(select(func.count()).select_from(HistoricoMovimentacao)) == 1


def test_manual_correction_is_append_only_and_paginated(pg_engine, setup):
    with pg_engine.begin() as c:
        first = append_automatic_movement(c, setup["passage"]).movement_id
        correction = append_manual_correction(
            c, equipamento_id=setup["equipment_a"], zona_destino_id=setup["zones"][2],
            movimentada_em=T + timedelta(hours=1), justificativa="  conferido fisicamente  ",
            registro_anterior_id=first,
        ).movement_id
        original = c.execute(select(HistoricoMovimentacao.__table__).where(
            HistoricoMovimentacao.id == first)).mappings().one()
        revised = c.execute(select(HistoricoMovimentacao.__table__).where(
            HistoricoMovimentacao.id == correction)).mappings().one()
        assert original["zona_destino_id"] == setup["zones"][1]
        assert revised["zona_origem_id"] == setup["zones"][1]
        assert revised["registro_anterior_id"] == first
        assert revised["justificativa"] == "conferido fisicamente"
        assert revised["passagem_id"] is None
        page = list_for_equipment(c, setup["equipment_a"], page=1, size=1)
        assert (page.total, page.pages, page.items[0].id) == (2, 2, correction)
        assert list_for_equipment(c, setup["equipment_a"], page=2, size=1).items[0].id == first
        assert list_for_equipment(c, setup["equipment_a"], page=1, size=10,
                                  inicio=T, fim=T + timedelta(hours=1)).total == 1


def test_equal_event_times_order_by_id(pg_engine, setup):
    with pg_engine.begin() as c:
        first = append_manual_correction(
            c, equipamento_id=setup["equipment_a"], zona_destino_id=setup["zones"][1],
            movimentada_em=T, justificativa="primeiro",
        ).movement_id
        second = append_manual_correction(
            c, equipamento_id=setup["equipment_a"], zona_destino_id=setup["zones"][2],
            movimentada_em=T, justificativa="segundo",
        ).movement_id
        assert [item.id for item in list_for_equipment(
            c, setup["equipment_a"], page=1, size=2).items] == [second, first]


def test_ambiguous_temporal_association_rejected(pg_engine, setup):
    with pg_engine.begin() as c:
        c.execute(AssociacaoTagEquipamento.__table__.insert().values(
            tag_id=setup["tag"], equipamento_id=setup["equipment_b"],
            inicio=T - timedelta(days=1), fim=T + timedelta(days=1),
        ))
        assert append_automatic_movement(c, setup["passage"]).status == "ambiguous_association"
        assert c.scalar(select(func.count()).select_from(HistoricoMovimentacao)) == 0


def test_database_rejects_invalid_auto_and_manual(pg_engine, setup):
    base = dict(equipamento_id=setup["equipment_a"], zona_destino_id=setup["zones"][1],
                movimentada_em=T)
    with pytest.raises(IntegrityError), pg_engine.begin() as c:
        c.execute(HistoricoMovimentacao.__table__.insert().values(
            **base, origem_registro="passagem_automatica"))
    with pytest.raises(IntegrityError), pg_engine.begin() as c:
        c.execute(HistoricoMovimentacao.__table__.insert().values(
            **base, origem_registro="correcao_manual", justificativa=" "))
    with pytest.raises(IntegrityError), pg_engine.begin() as c:
        c.execute(HistoricoMovimentacao.__table__.insert().values(
            **base, origem_registro="correcao_manual", justificativa="motivo",
            portal_id=999999,
        ))
    with pg_engine.begin() as c:
        append_automatic_movement(c, setup["passage"])
    with pytest.raises(IntegrityError), pg_engine.begin() as c:
        original = c.execute(select(HistoricoMovimentacao.__table__)).mappings().one()
        c.execute(HistoricoMovimentacao.__table__.insert().values(
            **{key: value for key, value in original.items() if key != "id"}
        ))


def test_api_lists_and_has_no_write_routes(pg_engine, setup):
    with pg_engine.begin() as c:
        append_automatic_movement(c, setup["passage"])

    def test_db():
        with Session(pg_engine) as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    try:
        with TestClient(app) as client:
            path = f"/equipamentos/{setup['equipment_a']}/movimentacoes"
            response = client.get(path, params={"page": 1, "size": 1})
            assert response.status_code == 200, response.text
            assert response.json()["items"][0]["epc"] == "EPC-X"
            assert response.json()["items"][0]["zona_destino"] == "zona 1"
            assert client.get("/equipamentos/999999/movimentacoes").status_code == 404
            assert client.get(path, params={"inicio": T.isoformat(),
                                            "fim": T.isoformat()}).status_code == 422
            assert client.patch(path + "/1", json={}).status_code == 404
            assert client.delete(path + "/1").status_code == 404
    finally:
        app.dependency_overrides.clear()
