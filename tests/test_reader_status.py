"""Status por relógio controlado, heartbeat sem tags e isolamento de segredos."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.database import get_db
from api.main import app
from api.router_status_hardware import aggregate, snapshot, status_context
from db.models import Antena, Leitor, LeituraBruta, MapeamentoAntenaPortal
from rfid_ingestion.config import Settings
from rfid_ingestion.mqtt_client import MqttReceiver
from rfid_ingestion.reader_status import (
    ReaderMonitor,
    StatusPolicy,
    classify,
    contacts,
    heartbeat_event,
)
from rfid_ingestion.repository import PersistenceError

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
TOPIC = "easy/dev/hupaa/portal-01/reader-01/heartbeat"


@pytest.mark.parametrize("seconds,health,state", [
    (None, None, "nunca_conectado"), (0, None, "online"), (29.999, None, "online"),
    (30, None, "degradado"), (89.999, None, "degradado"), (90, None, "offline"),
    (0, "degradado", "degradado"), (90, "degradado", "offline"),
])
def test_status_boundaries(seconds, health, state):
    seen = NOW - timedelta(seconds=seconds) if seconds is not None else None
    assert classify(seen, health, NOW, StatusPolicy())[0] == state


@pytest.mark.parametrize("first,last", [(0, 90), (90, 30), (30, 30), (float('nan'), 90), (30, float('inf'))])
def test_invalid_policy(first, last):
    with pytest.raises(ValueError):
        StatusPolicy(first, last)


def heartbeat(*, reader="reader-01", now=NOW, status="online", sent=None, retain=False):
    return heartbeat_event(TOPIC.replace("reader-01", reader), json.dumps({
        "status": status, "sent_at": (sent or now).isoformat()}).encode(), retain, StatusPolicy(), now)


@pytest.mark.parametrize("payload,retained", [
    (b"not-json-PRIVATE-SECRET", False), (b'{"password":"PRIVATE-SECRET"}', False),
    (b'[]', False), (b'{}', False), (b'x' * 1025, False),
    (json.dumps({"status": "online", "sent_at": NOW.isoformat()}).encode(), True),
    (json.dumps({"status": "online", "sent_at": "2026-10-15T12:00:00"}).encode(), False),
])
def test_bad_heartbeat_never_renews_or_echoes_payload(payload, retained):
    event = heartbeat_event(TOPIC, payload, retained, StatusPolicy(), NOW)
    assert not contacts([event])
    assert "PRIVATE-SECRET" not in json.dumps(event)


def test_heartbeat_replay_future_and_boundary():
    assert heartbeat(sent=NOW-timedelta(seconds=89.99))["heartbeat"]
    assert heartbeat(sent=NOW-timedelta(seconds=90))["heartbeat"] is None
    assert heartbeat(sent=NOW+timedelta(seconds=5))["heartbeat"]
    assert heartbeat(sent=NOW+timedelta(seconds=5.01))["heartbeat"] is None


@pytest.mark.parametrize("states,sides,expected", [
    ([], set(), "nunca_conectado"), (["nunca_conectado"]*2, {"a", "b"}, "nunca_conectado"),
    (["offline", "nunca_conectado"], {"a", "b"}, "offline"),
    (["online", "online"], {"a", "b"}, "online"),
    (["online", "online"], {"a"}, "degradado"),
    (["online", "offline"], {"a", "b"}, "degradado"),
    (["online", "nunca_conectado"], {"a", "b"}, "degradado"),
    (["degradado", "online"], {"a", "b"}, "degradado"),
])
def test_portal_aggregate(states, sides, expected):
    assert aggregate(states, sides)[0] == expected


@pytest.fixture
def readers(engine, truncate_all):
    with Session(engine) as db:
        for n in (1, 2, 3):
            db.add(Leitor(reader_id=f"reader-0{n}", fabricante="Simulado", modelo="Contrato software",
                          identificador_serial=f"status-{n}", endereco_rede="PRIVATE-SECRET"))
        db.commit()
    return engine


def test_two_readers_timeout_reconnect_no_tag_readings(readers, caplog):
    clock = [NOW]
    monitor = ReaderMonitor(readers, clock=lambda: clock[0])
    with caplog.at_level("INFO"):
        monitor.sweep()
        monitor.observe(contacts([heartbeat(), heartbeat(reader="reader-02")]))
        clock[0] += timedelta(seconds=30)
        monitor.sweep()
        monitor.observe(contacts([heartbeat(now=clock[0])]))
        clock[0] += timedelta(seconds=60)
        monitor.sweep()
        with Session(readers) as db:
            rows = db.scalars(select(Leitor).order_by(Leitor.reader_id)).all()
            assert [r.status for r in rows] == ["degradado", "offline", "nunca_conectado"]
            assert db.scalar(select(func.count()).select_from(LeituraBruta)) == 0
        monitor.observe(contacts([heartbeat(reader="reader-02", now=clock[0])]))
        with Session(readers) as db:
            assert db.scalar(select(Leitor.status).where(Leitor.reader_id == "reader-02")) == "online"
    assert monitor.transitions >= 8
    assert 'reader_status_changed' in caplog.text
    assert 'PRIVATE-SECRET' not in caplog.text


def test_duplicate_heartbeat_and_reading_do_not_clear_reported_failure(readers):
    monitor = ReaderMonitor(readers, clock=lambda: NOW)
    monitor.observe(contacts([heartbeat(status="degradado")]))
    monitor.observe(contacts([heartbeat(status="online")]))  # mesmo sent_at: replay
    monitor.observe([{"reader_id": "reader-01", "seen": NOW+timedelta(seconds=1), "source": "leitura"}])
    monitor.observe([{"reader_id": "reader-01", "seen": NOW-timedelta(seconds=1), "source": "leitura"}])
    with Session(readers) as db:
        row = db.scalar(select(Leitor).where(Leitor.reader_id == "reader-01"))
        assert row.status == "degradado"
        assert row.ultimo_contato_em == NOW+timedelta(seconds=1)
    monitor.observe(contacts([heartbeat(now=NOW+timedelta(seconds=2))]))
    with Session(readers) as db:
        assert db.scalar(select(Leitor.status).where(Leitor.reader_id == "reader-01")) == "online"


def test_unknown_and_inactive_reader_do_not_gain_contact(readers):
    with Session(readers) as db:
        db.scalar(select(Leitor).where(Leitor.reader_id == "reader-02")).ativo = False
        db.commit()
    monitor = ReaderMonitor(readers, clock=lambda: NOW)
    monitor.observe(contacts([heartbeat(reader="unknown"), heartbeat(reader="reader-02")]))
    with Session(readers) as db:
        assert all(r.ultimo_contato_em is None for r in db.scalars(select(Leitor)))


def test_two_reader_portal_loses_component_and_recovers(readers):
    from tools.lab_launcher.seed import semear
    with Session(readers) as db:
        semear(db)
        second = db.scalar(select(Leitor).where(Leitor.reader_id == 'reader-02'))
        antenna = db.scalar(select(Antena).where(Antena.porta_numero == 2))
        antenna.leitor_id = second.id
        for mapping in db.scalars(select(MapeamentoAntenaPortal)):
            mapping.inicio = NOW-timedelta(seconds=1)
        db.commit()
    clock = [NOW]
    monitor = ReaderMonitor(readers, clock=lambda: clock[0])
    monitor.observe(contacts([heartbeat(), heartbeat(reader='reader-02')]))
    with Session(readers) as db:
        assert snapshot(db, clock[0], StatusPolicy()).portais[0].status == 'online'
    clock[0] += timedelta(seconds=90)
    monitor.observe(contacts([heartbeat(now=clock[0])]))
    with Session(readers) as db:
        portal = snapshot(db, clock[0], StatusPolicy()).portais[0]
        assert portal.status == 'degradado'
        assert portal.motivo == 'falha_parcial_ou_degradacao'
    monitor.observe(contacts([heartbeat(reader='reader-02', now=clock[0])]))
    with Session(readers) as db:
        assert snapshot(db, clock[0], StatusPolicy()).portais[0].status == 'online'


def test_api_expires_without_ingestor_and_excludes_secrets(readers):
    clock = [NOW]
    monitor = ReaderMonitor(readers, clock=lambda: clock[0])
    monitor.observe(contacts([heartbeat()]))
    def dependency():
        with Session(readers) as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    app.dependency_overrides[status_context] = lambda: (clock[0], StatusPolicy())
    try:
        with TestClient(app) as client:
            first = client.get('/leitores/status')
            assert first.status_code == 200
            assert first.json()['leitores'][0]['status'] == 'online'
            clock[0] += timedelta(seconds=90)
            second = client.get('/leitores/status')
            assert second.json()['leitores'][0]['status'] == 'offline'
            assert second.json()['leitores'][2]['status'] == 'nunca_conectado'
            assert 'PRIVATE-SECRET' not in second.text
            assert 'parametros_ingestao' not in second.text
            assert client.get('/portais/status').json() == []
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(status_context, None)


@pytest.mark.parametrize("failure", [False, True])
def test_heartbeat_ack_after_status_commit_without_reading_repository(tmp_path, failure):
    with patch('rfid_ingestion.mqtt_client.create_client') as factory:
        client = factory.return_value
        client.ack.return_value = 0
        monitor = Mock(policy=StatusPolicy())
        def observe(values):
            client.ack.assert_not_called()
            assert values[0]['source'] == 'heartbeat'
            if failure:
                raise PersistenceError('PRIVATE-SECRET')
        monitor.observe.side_effect = observe
        repository = Mock()
        receiver = MqttReceiver(Settings(mqtt_heartbeat_topic='easy/+/+/+/+/heartbeat'),
                                Mock(), repository, reader_monitor=monitor)
        message = Mock(mid=4, qos=1, retain=False, topic=TOPIC,
                       payload=json.dumps({'status':'online','sent_at':datetime.now(timezone.utc).isoformat()}).encode())
        receiver._on_message(client, None, message)
        receiver._flush_pending()
        repository.persist.assert_not_called()
        repository.persist_many.assert_not_called()
        if failure:
            client.ack.assert_not_called()
            assert receiver.database_unavailable.is_set()
        else:
            client.ack.assert_called_once_with(4, 1)
