"""Topologia temporal, persistência e fluxo real de debounce da ISS-015."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from db.models import (
    Antena,
    Equipamento,
    HistoricoMovimentacao,
    Leitor,
    LeituraBruta,
    MapeamentoAntenaPortal,
    Passagem,
    Portal,
    TipoEquipamento,
    Zona,
)
from rfid_inference.debounce import ConsolidatedObservation
from rfid_inference.passage import PassageDetector
from rfid_inference.passage_repository import PassageRepository
from rfid_inference.passage_service import PassageInferenceService
from rfid_ingestion.config import Settings
from rfid_ingestion.mqtt_client import MqttReceiver
from rfid_ingestion.persistence import JsonlEventStore
from rfid_ingestion.repository import RawReadingRepository

T0 = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)


def mqtt_message(mid, antenna, timestamp):
    return Mock(
        mid=mid, qos=1, retain=False,
        topic="easy/test/hupaa/portal-01/reader-01/readings",
        payload=json.dumps({
            "epc": "EPC-INTEGRACAO", "antenna": antenna,
            "rssi": -3880, "timestamp": timestamp,
        }).encode(),
    )


def _observation(antenna, first, last=None, reading=1):
    last = first if last is None else last
    return ConsolidatedObservation(
        "EPC-INTEGRACAO", antenna, T0 + timedelta(seconds=first),
        T0 + timedelta(seconds=last), 1, reading, reading,
        f"event-{reading}", f"event-{reading}", None, None, None,
    )


@pytest.fixture
def mapped_portal(pg_engine, topology):
    with pg_engine.begin() as connection:
        sector_id = connection.scalar(
            select(Zona.setor_id).where(Zona.id == topology["zone"])
        )
        zone_b = connection.execute(
            Zona.__table__.insert().values(
                setor_id=sector_id, nome="lado b", nome_normalizado="lado b"
            ).returning(Zona.id)
        ).scalar_one()
        portal = connection.execute(
            Portal.__table__.insert().values(
                nome="Portal teste", zona_a_id=topology["zone"], zona_b_id=zone_b
            ).returning(Portal.id)
        ).scalar_one()
        antenna_b = connection.execute(
            Antena.__table__.insert().values(
                leitor_id=topology["reader"], porta_numero=2,
                zona_associada_id=zone_b, funcao="indefinido",
            ).returning(Antena.id)
        ).scalar_one()
        for antenna, side, zone in (
            (topology["antenna"], "a", topology["zone"]),
            (antenna_b, "b", zone_b),
        ):
            connection.execute(
                MapeamentoAntenaPortal.__table__.insert().values(
                    antena_id=antenna, portal_id=portal, lado=side,
                    zona_id=zone, funcao="auxiliar", inicio=T0 - timedelta(days=1),
                )
            )
    return portal, topology["antenna"], antenna_b, topology["zone"], zone_b


def test_temporal_mapping_boundaries_and_ambiguity(pg_engine, mapped_portal):
    portal, antenna_a, _, _, zone_b = mapped_portal
    relogio = [0.0]
    repo = PassageRepository(pg_engine, clock=lambda: relogio[0])
    assert repo.resolve(_observation(antenna_a, 0, 1)).portal_id == portal
    with pg_engine.begin() as connection:
        connection.execute(
            MapeamentoAntenaPortal.__table__.update().where(
                MapeamentoAntenaPortal.antena_id == antenna_a
            ).values(fim=T0)
        )
        new_id = connection.execute(
            MapeamentoAntenaPortal.__table__.insert().values(
                antena_id=antenna_a, portal_id=portal, lado="b",
                zona_id=zone_b, funcao="auxiliar", inicio=T0,
            ).returning(MapeamentoAntenaPortal.id)
        ).scalar_one()
    # Dentro do TTL o cache ainda vê o mapeamento antigo, sem fim.
    assert repo.resolve(_observation(antenna_a, 0)).side == "a"
    relogio[0] += PassageRepository.MAPPING_TTL_SECONDS + 1
    assert repo.resolve(_observation(antenna_a, -1, -0.1)).side == "a"
    at_boundary = repo.resolve(_observation(antenna_a, 0))
    assert at_boundary.mapping_id == new_id
    assert at_boundary.side == "b"
    assert repo.resolve(_observation(antenna_a, -0.1, 0.1)) is None
    assert repo.resolve(_observation(999999, 0)) is None
    # Mesmo com um mapeamento que cobre T, outra versão sobreposta invalida a resolução.
    with pg_engine.begin() as connection:
        connection.execute(
            MapeamentoAntenaPortal.__table__.insert().values(
                antena_id=antenna_a, portal_id=portal, lado="a",
                zona_id=mapped_portal[3], funcao="auxiliar",
                inicio=T0 - timedelta(seconds=1), fim=T0 + timedelta(seconds=1),
            )
        )
    relogio[0] += PassageRepository.MAPPING_TTL_SECONDS + 1
    assert repo.resolve(_observation(antenna_a, 0)) is None


def test_multiple_antennas_same_side_and_different_readers(pg_engine, mapped_portal):
    portal, antenna_a, antenna_b, zone_a, _ = mapped_portal
    with pg_engine.begin() as connection:
        reader_2 = connection.execute(
            Leitor.__table__.insert().values(
                reader_id="reader-02", identificador_serial="serial-02",
                fabricante="teste", modelo="teste",
            ).returning(Leitor.id)
        ).scalar_one()
        antenna_a2 = connection.execute(
            Antena.__table__.insert().values(
                leitor_id=reader_2, porta_numero=1,
                zona_associada_id=zone_a, funcao="indefinido",
            ).returning(Antena.id)
        ).scalar_one()
        connection.execute(
            MapeamentoAntenaPortal.__table__.insert().values(
                antena_id=antenna_a2, portal_id=portal, lado="a",
                zona_id=zone_a, funcao="auxiliar", inicio=T0 - timedelta(days=1),
            )
        )
    repository = PassageRepository(pg_engine)
    detector = PassageDetector(timedelta(seconds=3))
    for antenna, instant in ((antenna_a, 0), (antenna_a2, 1)):
        assert detector.add(repository.resolve(_observation(antenna, instant))) is None
    passage = detector.add(repository.resolve(_observation(antenna_b, 2)))
    assert passage is not None
    assert passage.first_antenna_id == antenna_a2
    assert passage.second_antenna_id == antenna_b


def test_pipeline_raw_debounce_passage_and_replay(pg_engine, mapped_portal, tmp_path):
    portal, antenna_a, antenna_b, _, _ = mapped_portal
    with pg_engine.begin() as connection:
        kind = connection.execute(
            TipoEquipamento.__table__.insert().values(
                nome="tipo teste", nome_normalizado="tipo teste"
            ).returning(TipoEquipamento.id)
        ).scalar_one()
        equipment = connection.execute(
            Equipamento.__table__.insert().values(
                nome="equipamento teste", tipo_id=kind,
                identificador_interno="ISS015-1",
                identificador_interno_normalizado="iss015-1",
            ).returning(Equipamento.id)
        ).scalar_one()
    repository = PassageRepository(pg_engine)
    service = PassageInferenceService(PassageDetector(timedelta(seconds=3)), repository)
    observations = []

    def handle(observation):
        observations.append(observation)
        service.handle_observation(observation)

    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        client = factory.return_value
        client.ack.return_value = 0
        receiver = MqttReceiver(
            Settings(), JsonlEventStore(tmp_path / "events.jsonl"),
            RawReadingRepository(pg_engine), observation_handler=handle,
            observation_tick_handler=service.tick,
        )
        messages = [
            mqtt_message(1, 1, "2026-09-22T12:00:00.000Z"),
            mqtt_message(2, 1, "2026-09-22T12:00:00.100Z"),
            mqtt_message(3, 2, "2026-09-22T12:00:01.000Z"),
            mqtt_message(4, 2, "2026-09-22T12:00:01.100Z"),
        ]
        for message in (*messages, messages[0]):
            receiver._on_message(client, None, message)
            receiver._flush_pending()
        receiver.flush_debounce()

    with pg_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(LeituraBruta)) == 4
        assert connection.scalar(select(func.count()).select_from(Passagem)) == 1
        passage = connection.execute(select(Passagem.__table__)).one()
        assert passage.epc == "EPC-INTEGRACAO"
        assert passage.portal_id == portal
        assert passage.antena_origem_id == antenna_a
        assert passage.antena_destino_id == antenna_b
        assert passage.leitura_origem_id == observations[0].last_reading_id
        assert passage.leitura_destino_id == observations[1].first_reading_id
        assert passage.detectada_em == T0 + timedelta(seconds=1.1)
        assert passage.direcao is None
        assert connection.scalar(select(func.count()).select_from(HistoricoMovimentacao)) == 0
        location = connection.execute(
            select(Equipamento.ultima_zona_id, Equipamento.ultima_deteccao_em,
                   Equipamento.ultima_passagem_id).where(Equipamento.id == equipment)
        ).one()
        assert location == (None, None, None)
    assert len(observations) == 2
    assert client.ack.call_count == 5
    assert service.detector.counters.passages_confirmed == 1

    # Replay da mesma evidência, inclusive após reiniciar o detector.
    again = PassageInferenceService(PassageDetector(timedelta(seconds=3)), repository)
    for observation in observations:
        again.handle_observation(observation)
    assert again.detector.counters.passages_duplicates == 1
    with pg_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Passagem)) == 1
        with pytest.raises(IntegrityError):
            connection.execute(
                Passagem.__table__.insert().values(
                    epc=passage.epc, portal_id=portal,
                    antena_origem_id=antenna_a, antena_destino_id=antenna_b,
                    leitura_origem_id=passage.leitura_origem_id,
                    leitura_destino_id=passage.leitura_destino_id,
                    detectada_em=T0,
                )
            )


def test_origin_active_detects_reflection_from_raw_readings(pg_engine, mapped_portal):
    _, antenna_a, antenna_b, _, _ = mapped_portal
    repo = PassageRepository(pg_engine)
    origin = repo.resolve(_observation(antenna_a, 0, 1, reading=1))
    destination = repo.resolve(_observation(antenna_b, 2, 2.5, reading=2))
    grace, hold = timedelta(milliseconds=300), timedelta(seconds=1)

    def read(antenna, second, event):
        with pg_engine.begin() as connection:
            connection.execute(LeituraBruta.__table__.insert().values(
                event_id=f"sha256:{event:064x}", antena_id=antenna, epc="EPC-INTEGRACAO",
                lido_em=T0 + timedelta(seconds=second)))

    # Leitura de A dentro da sobreposição tolerada e depois do hold: travessia real.
    read(antenna_a, 2.2, 1)
    read(antenna_a, 3.6, 2)
    assert repo.origin_active(origin, destination, grace=grace, hold=hold) is False
    # A continua lendo a tag enquanto B a vê: reflexão, não passagem.
    read(antenna_a, 3.0, 3)
    assert repo.origin_active(origin, destination, grace=grace, hold=hold) is True


def test_mapeamento_em_cache_evita_consulta_por_observacao(pg_engine, mapped_portal):
    from sqlalchemy import event as sql_event
    _portal, antenna_a, *_ = mapped_portal
    repo = PassageRepository(pg_engine)
    consultas = []
    sql_event.listen(pg_engine, "before_cursor_execute",
                     lambda *_a: consultas.append(1))
    for segundo in range(10):
        assert repo.resolve(_observation(antenna_a, segundo)) is not None
    assert len(consultas) == 1
    # Antena sem mapeamento em cache: consulta de novo antes de desistir.
    assert repo.resolve(_observation(999999, 0)) is None
    assert len(consultas) == 2
    assert repo.resolve(_observation(999999, 1)) is None
    assert len(consultas) == 3


def test_previous_observation_restores_last_side_and_direction_after_restart(
        pg_engine, mapped_portal):
    from rfid_inference.direction_repository import DirectionRepository
    from rfid_inference.direction_service import DirectionInferenceService

    portal, antenna_a, antenna_b, zone_a, zone_b = mapped_portal
    with pg_engine.begin() as connection:
        ids = [connection.execute(LeituraBruta.__table__.insert().values(
            event_id=f"sha256:{event:064x}", antena_id=antenna, epc="EPC-INTEGRACAO",
            lido_em=T0 + timedelta(seconds=second)).returning(LeituraBruta.id)).scalar_one()
            for event, antenna, second in ((1, antenna_a, 0), (2, antenna_a, 0.01),
                                           (3, antenna_b, 0.03))]
    repo = PassageRepository(pg_engine)
    destination = repo.resolve(ConsolidatedObservation(
        "EPC-INTEGRACAO", antenna_b, T0 + timedelta(seconds=0.03),
        T0 + timedelta(seconds=0.03), 1, ids[2], ids[2], "e3", "e3", None, None, None))
    previous = repo.previous_observation(destination)
    assert (previous.side, previous.last_reading_id) == ("a", ids[1])

    # Ingestor recém-iniciado: o lado A vem do banco e a passagem sai mesmo
    # com evidências a 20 ms (mesmo leitor: ordem de chegada).
    direction = DirectionInferenceService(DirectionRepository(pg_engine), 100)
    service = PassageInferenceService(PassageDetector(None), repo, monotonic_clock=lambda: 0,
                                      passage_persisted=direction.process_pending)
    service.handle_observation(ConsolidatedObservation(
        "EPC-INTEGRACAO", antenna_b, T0 + timedelta(seconds=0.03),
        T0 + timedelta(seconds=0.03), 1, ids[2], ids[2], f"sha256:{3:064x}",
        f"sha256:{3:064x}", None, None, None))
    with pg_engine.connect() as connection:
        row = connection.execute(select(Passagem.direcao_status, Passagem.direcao,
                                        Passagem.direcao_regra, Passagem.zona_destino_id)).one()
    assert tuple(row) == ("confirmed", "a_para_b", "arrival_order_v1", zone_b)
