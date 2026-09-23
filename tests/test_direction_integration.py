"""Persistência, topologia histórica e fluxo completo da ISS-016 em PostgreSQL."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from db.models import (
    Antena,
    AssociacaoTagEquipamento,
    Equipamento,
    HistoricoMovimentacao,
    Leitor,
    LeituraBruta,
    MapeamentoAntenaPortal,
    Passagem,
    Portal,
    Tag,
    TipoEquipamento,
    Zona,
)
from rfid_inference.direction_repository import DirectionRepository
from rfid_inference.direction_service import DirectionInferenceService
from rfid_inference.passage import PassageDetector
from rfid_inference.passage_repository import PassageRepository
from rfid_inference.passage_service import PassageInferenceService
from rfid_ingestion.config import Settings
from rfid_ingestion.mqtt_client import MqttReceiver
from rfid_ingestion.persistence import JsonlEventStore
from rfid_ingestion.repository import RawReadingRepository
from rfid_location.service import LocationProjectionService

T0 = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)


@pytest.fixture
def portal_setup(pg_engine, topology):
    with pg_engine.begin() as connection:
        sector_id = connection.scalar(select(Zona.setor_id).where(Zona.id == topology["zone"]))
        zone_b = connection.execute(Zona.__table__.insert().values(
            setor_id=sector_id, nome="zona B", nome_normalizado="zona b"
        ).returning(Zona.id)).scalar_one()
        portal = connection.execute(Portal.__table__.insert().values(
            nome="portal ISS-016", zona_a_id=topology["zone"], zona_b_id=zone_b
        ).returning(Portal.id)).scalar_one()
        antenna_b = connection.execute(Antena.__table__.insert().values(
            leitor_id=topology["reader"], porta_numero=2,
            zona_associada_id=zone_b, funcao="indefinido"
        ).returning(Antena.id)).scalar_one()
        for antenna, side, zone in (
            (topology["antenna"], "a", topology["zone"]),
            (antenna_b, "b", zone_b),
        ):
            connection.execute(MapeamentoAntenaPortal.__table__.insert().values(
                antena_id=antenna, portal_id=portal, lado=side,
                zona_id=zone, funcao="auxiliar", inicio=T0 - timedelta(days=1),
            ))
    return {"portal": portal, "a": topology["antenna"], "b": antenna_b,
            "zone_a": topology["zone"], "zone_b": zone_b}


def insert_passage(engine, setup, *, first="a", second="b", delta_ms=101):
    with engine.begin() as connection:
        evidence = []
        for index, (side, at) in enumerate(((first, T0),
                                           (second, T0 + timedelta(milliseconds=delta_ms)))):
            reading_id = connection.execute(LeituraBruta.__table__.insert().values(
                event_id=f"event-{first}-{second}-{delta_ms}-{index}",
                antena_id=setup[side], epc="EPC-ISS016", lido_em=at,
            ).returning(LeituraBruta.id)).scalar_one()
            evidence.append(reading_id)
        passage_id = connection.execute(Passagem.__table__.insert().values(
            epc="EPC-ISS016", portal_id=setup["portal"],
            antena_origem_id=setup[first], antena_destino_id=setup[second],
            leitura_origem_id=evidence[0], leitura_destino_id=evidence[1],
            detectada_em=T0 + timedelta(milliseconds=delta_ms),
        ).returning(Passagem.id)).scalar_one()
    return passage_id


@pytest.mark.parametrize("first,second,direction,zones", [
    ("a", "b", "a_para_b", ("zone_a", "zone_b")),
    ("b", "a", "b_para_a", ("zone_b", "zone_a")),
])
def test_persisted_direction_and_retry(pg_engine, portal_setup, first, second, direction, zones):
    passage_id = insert_passage(pg_engine, portal_setup, first=first, second=second)
    service = DirectionInferenceService(DirectionRepository(pg_engine), 100)
    with pg_engine.connect() as connection:
        assert connection.scalar(select(Passagem.direcao).where(Passagem.id == passage_id)) is None
    result = service.process(passage_id)
    assert result.direction == direction
    assert service.process(passage_id) is None
    with pg_engine.connect() as connection:
        passage = connection.execute(select(Passagem.__table__).where(
            Passagem.id == passage_id
        )).one()
        assert passage.direcao == direction
        assert passage.direcao_status == "confirmed"
        assert passage.direcao_regra == "temporal_side_order_v1"
        assert (passage.zona_origem_id, passage.zona_destino_id) == tuple(
            portal_setup[key] for key in zones
        )
        assert connection.scalar(select(func.count()).select_from(Passagem)) == 1
    assert service.counters.passages_processed == 1


@pytest.mark.parametrize("delta,status", [(0, "ambiguous"), (50, "ambiguous"),
                                          (100, "ambiguous"), (101, "confirmed")])
def test_temporal_boundary_in_database(pg_engine, portal_setup, delta, status):
    passage_id = insert_passage(pg_engine, portal_setup, delta_ms=delta)
    result = DirectionInferenceService(DirectionRepository(pg_engine), 100).process(passage_id)
    assert result.status == status
    with pg_engine.connect() as connection:
        passage = connection.execute(select(Passagem.__table__).where(
            Passagem.id == passage_id
        )).one()
        assert passage.direcao_status == status
        if status == "ambiguous":
            assert passage.direcao == "indeterminada"
            assert passage.zona_origem_id is passage.zona_destino_id is None


def test_historical_mapping_and_half_open_boundaries(pg_engine, portal_setup):
    passage_id = insert_passage(pg_engine, portal_setup)
    boundary = T0 + timedelta(seconds=1)
    with pg_engine.begin() as connection:
        connection.execute(MapeamentoAntenaPortal.__table__.update().where(
            MapeamentoAntenaPortal.portal_id == portal_setup["portal"]
        ).values(fim=boundary))
        for side, zone in (("a", "zone_a"), ("b", "zone_b")):
            connection.execute(MapeamentoAntenaPortal.__table__.insert().values(
                antena_id=portal_setup[side], portal_id=portal_setup["portal"],
                lado=side, zona_id=portal_setup[zone], funcao="auxiliar",
                inicio=boundary,
            ))
    repository = DirectionRepository(pg_engine)
    context = repository.load(passage_id)
    assert len(context.first.mappings) == len(context.second.mappings) == 1
    assert context.zone_a_id == portal_setup["zone_a"]
    assert DirectionInferenceService(repository, 100).process(passage_id).direction == "a_para_b"
    # Inclusivo em início, exclusivo em fim.
    with pg_engine.begin() as connection:
        reading_id = connection.execute(LeituraBruta.__table__.insert().values(
            event_id="boundary-reading", antena_id=portal_setup["a"],
            epc="EPC-boundary", lido_em=boundary,
        ).returning(LeituraBruta.id)).scalar_one()
        other_id = connection.execute(LeituraBruta.__table__.insert().values(
            event_id="boundary-reading-b", antena_id=portal_setup["b"],
            epc="EPC-boundary", lido_em=boundary + timedelta(milliseconds=101),
        ).returning(LeituraBruta.id)).scalar_one()
        new_passage = connection.execute(Passagem.__table__.insert().values(
            epc="EPC-boundary", portal_id=portal_setup["portal"],
            antena_origem_id=portal_setup["a"], antena_destino_id=portal_setup["b"],
            leitura_origem_id=reading_id, leitura_destino_id=other_id,
            detectada_em=boundary + timedelta(milliseconds=101),
        ).returning(Passagem.id)).scalar_one()
    assert DirectionInferenceService(repository, 100).process(new_passage).direction == "a_para_b"


@pytest.mark.parametrize("damage", ["missing", "overlap", "other_portal", "wrong_zone"])
def test_unresolved_historical_topology_is_unknown(pg_engine, portal_setup, damage):
    passage_id = insert_passage(pg_engine, portal_setup)
    with pg_engine.begin() as connection:
        if damage == "missing":
            connection.execute(MapeamentoAntenaPortal.__table__.delete().where(
                MapeamentoAntenaPortal.antena_id == portal_setup["a"]
            ))
        elif damage == "overlap":
            connection.execute(MapeamentoAntenaPortal.__table__.insert().values(
                antena_id=portal_setup["a"], portal_id=portal_setup["portal"],
                lado="a", zona_id=portal_setup["zone_a"], funcao="auxiliar",
                inicio=T0 - timedelta(seconds=1), fim=T0 + timedelta(seconds=1),
            ))
        elif damage == "other_portal":
            other_portal = connection.execute(Portal.__table__.insert().values(
                nome="outro", zona_a_id=portal_setup["zone_a"],
                zona_b_id=portal_setup["zone_b"],
            ).returning(Portal.id)).scalar_one()
            connection.execute(MapeamentoAntenaPortal.__table__.update().where(
                MapeamentoAntenaPortal.antena_id == portal_setup["a"]
            ).values(portal_id=other_portal))
        else:
            connection.execute(MapeamentoAntenaPortal.__table__.update().where(
                MapeamentoAntenaPortal.antena_id == portal_setup["a"]
            ).values(zona_id=portal_setup["zone_b"]))
    result = DirectionInferenceService(DirectionRepository(pg_engine), 100).process(passage_id)
    assert result.status == "unknown"
    assert result.destination_zone_id is None


def test_unknown_retry_cannot_degrade_confirmed(pg_engine, portal_setup):
    passage_id = insert_passage(pg_engine, portal_setup)
    repository = DirectionRepository(pg_engine)
    service = DirectionInferenceService(repository, 100)
    confirmed = service.process(passage_id)
    with pg_engine.begin() as connection:
        connection.execute(MapeamentoAntenaPortal.__table__.delete().where(
            MapeamentoAntenaPortal.antena_id == portal_setup["a"]
        ))
    assert service.process(passage_id) is None
    assert repository.persist(confirmed) is False
    with pg_engine.connect() as connection:
        assert connection.scalar(select(Passagem.direcao_status).where(
            Passagem.id == passage_id
        )) == "confirmed"


def test_multiple_antennas_and_readers_use_mapping_only(pg_engine, portal_setup):
    with pg_engine.begin() as connection:
        reader = connection.execute(Leitor.__table__.insert().values(
            reader_id="reader-different", identificador_serial="serial-different",
            fabricante="teste", modelo="teste",
        ).returning(Leitor.id)).scalar_one()
        antenna_a2 = connection.execute(Antena.__table__.insert().values(
            leitor_id=reader, porta_numero=7,
            zona_associada_id=portal_setup["zone_a"], funcao="indefinido",
        ).returning(Antena.id)).scalar_one()
        antenna_b2 = connection.execute(Antena.__table__.insert().values(
            leitor_id=reader, porta_numero=8,
            zona_associada_id=portal_setup["zone_b"], funcao="indefinido",
        ).returning(Antena.id)).scalar_one()
        for antenna, side, zone in ((antenna_a2, "a", portal_setup["zone_a"]),
                                    (antenna_b2, "b", portal_setup["zone_b"])):
            connection.execute(MapeamentoAntenaPortal.__table__.insert().values(
                antena_id=antenna, portal_id=portal_setup["portal"], lado=side,
                zona_id=zone, funcao="auxiliar", inicio=T0 - timedelta(days=1),
            ))
    setup = portal_setup | {"a": antenna_a2, "b": antenna_b2}
    passage_id = insert_passage(pg_engine, setup)
    result = DirectionInferenceService(DirectionRepository(pg_engine), 100).process(passage_id)
    assert result.direction == "a_para_b"
    assert result.destination_zone_id == portal_setup["zone_b"]


def _message(mid, antenna, at):
    return Mock(
        mid=mid, qos=1, retain=False,
        topic="easy/test/hupaa/portal-01/reader-01/readings",
        payload=json.dumps({
            "epc": "EPC-E2E", "antenna": antenna,
            "rssi": -3880, "timestamp": at,
        }).encode(),
    )


@pytest.mark.parametrize("second_time,status", [
    ("2026-09-22T12:00:01.000Z", "confirmed"),
    ("2026-09-22T12:00:00.050Z", "ambiguous"),
])
def test_full_pipeline_projects_only_confirmed_passages(
    pg_engine, portal_setup, tmp_path, second_time, status,
):
    with pg_engine.begin() as connection:
        kind = connection.execute(TipoEquipamento.__table__.insert().values(
            nome="tipo ISS-016", nome_normalizado="tipo iss-016"
        ).returning(TipoEquipamento.id)).scalar_one()
        equipment = connection.execute(Equipamento.__table__.insert().values(
            nome="equipamento ISS-016", tipo_id=kind,
            identificador_interno="ISS016-1",
            identificador_interno_normalizado="iss016-1",
        ).returning(Equipamento.id)).scalar_one()
        tag = connection.scalar(Tag.__table__.insert().values(
            epc="EPC-E2E").returning(Tag.id))
        connection.execute(AssociacaoTagEquipamento.__table__.insert().values(
            tag_id=tag, equipamento_id=equipment, inicio=T0 - timedelta(days=1),
        ))
    location = LocationProjectionService(pg_engine)
    direction = DirectionInferenceService(
        DirectionRepository(pg_engine), 100,
        confirmed_handler=location.process_passage,
    )
    passage = PassageInferenceService(
        PassageDetector(timedelta(seconds=3)), PassageRepository(pg_engine),
        passage_persisted=direction.process_pending,
    )
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        client = factory.return_value
        client.ack.return_value = 0
        receiver = MqttReceiver(
            Settings(), JsonlEventStore(tmp_path / "events.jsonl"),
            RawReadingRepository(pg_engine),
            observation_handler=passage.handle_observation,
            observation_tick_handler=passage.tick,
        )
        receiver._on_message(client, None, _message(1, 1, "2026-09-22T12:00:00.000Z"))
        receiver._on_message(client, None, _message(2, 2, second_time))
        receiver.flush_debounce()
    with pg_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(LeituraBruta)) == 2
        assert connection.scalar(select(func.count()).select_from(Passagem)) == 1
        row = connection.execute(select(Passagem.__table__)).one()
        assert row.portal_id == portal_setup["portal"]
        assert row.direcao_status == status
        assert row.direcao == ("a_para_b" if status == "confirmed" else "indeterminada")
        assert row.zona_origem_id == (portal_setup["zone_a"] if status == "confirmed" else None)
        assert row.zona_destino_id == (portal_setup["zone_b"] if status == "confirmed" else None)
        projected = connection.execute(select(
            Equipamento.ultima_zona_id, Equipamento.ultima_deteccao_em,
            Equipamento.ultima_passagem_id, Equipamento.ultima_movimentacao_id,
        ).where(Equipamento.id == equipment)).one()
        if status == "confirmed":
            movement = connection.execute(
                select(HistoricoMovimentacao.__table__)
            ).mappings().one()
            assert projected == (
                portal_setup["zone_b"], row.detectada_em, row.id, movement["id"],
            )
            assert movement["zona_origem_id"] == portal_setup["zone_a"]
            assert movement["zona_destino_id"] == portal_setup["zone_b"]
            assert movement["movimentada_em"] == row.detectada_em
        else:
            assert projected == (None, None, None, None)
            assert connection.scalar(select(func.count()).select_from(HistoricoMovimentacao)) == 0


def test_database_constraints_reject_invalid_state_and_fk(pg_engine, portal_setup):
    passage_id = insert_passage(pg_engine, portal_setup)
    with pytest.raises(IntegrityError), pg_engine.begin() as connection:
        connection.execute(Passagem.__table__.update().where(Passagem.id == passage_id).values(
            direcao="entrada", direcao_status="confirmed", direcao_regra="invalid",
            zona_origem_id=portal_setup["zone_a"], zona_destino_id=portal_setup["zone_b"],
        ))
    with pytest.raises(IntegrityError), pg_engine.begin() as connection:
        connection.execute(Passagem.__table__.update().where(Passagem.id == passage_id).values(
            direcao="a_para_b", direcao_status="confirmed", direcao_regra="invalid",
            zona_origem_id=999999, zona_destino_id=portal_setup["zone_b"],
        ))
