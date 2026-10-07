"""ACK somente após auditoria e resultado definitivo de persistência."""

import json
import time
from threading import Thread
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import func, select

from db.models import LeituraBruta
from rfid_ingestion.config import Settings
from rfid_ingestion.mqtt_client import MqttReceiver
from rfid_ingestion.persistence import JsonlEventStore
from rfid_ingestion.repository import PersistenceError, PersistenceResult, RawReadingRepository


def message(payload=None):
    return Mock(mid=42, qos=1, retain=False,
                topic="easy/test/hupaa/portal-01/reader-01/readings",
                payload=payload if payload is not None else json.dumps({
                    "epc": "PRIVATE-EPC", "antenna": 1, "rssi": -3880,
                    "timestamp": "2026-09-01T13:00:00Z"}).encode())


@pytest.mark.parametrize("status", ["inserted", "duplicate"])
def test_ack_after_audit_and_database(tmp_path, status):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        client = factory.return_value
        client.ack.return_value = 0
        path = tmp_path / "audit.jsonl"

        def persist(event):
            assert json.loads(path.read_text())["canonical_event"] == event["canonical_event"]
            client.ack.assert_not_called()
            return PersistenceResult(status)

        receiver = MqttReceiver(Settings(), JsonlEventStore(path), Mock(persist=persist))
        receiver._on_message(client, None, message())
        receiver._flush_pending()
        client.manual_ack_set.assert_called_once_with(True)
        client.ack.assert_called_once_with(42, 1)
        assert not receiver.failed.is_set()


def test_database_failure_no_ack_and_no_secrets(tmp_path, caplog):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        repository = Mock(persist=Mock(side_effect=PersistenceError("PRIVATE-CONNECTION")))
        receiver = MqttReceiver(Settings(), JsonlEventStore(tmp_path / "audit.jsonl"), repository)
        receiver._on_message(factory.return_value, None, message())
        receiver._flush_pending()
        factory.return_value.ack.assert_not_called()
        assert receiver.database_unavailable.is_set()
        assert not receiver.failed.is_set()
        assert "PRIVATE" not in caplog.text
        factory.return_value.disconnect.assert_called_once()


@pytest.mark.parametrize("kind,reason", [
    ("invalid", "invalid_input"), ("reader", "unknown_reader"),
    ("antenna", "unknown_antenna"),
])
def test_permanent_rejection_audited_and_acked(pg_engine, topology, tmp_path, kind, reason):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        client = factory.return_value
        client.ack.return_value = 0
        path = tmp_path / "audit.jsonl"
        receiver = MqttReceiver(Settings(), JsonlEventStore(path), RawReadingRepository(pg_engine))
        incoming = message()
        if kind == "invalid":
            incoming.payload = b"{invalid"
        elif kind == "reader":
            incoming.topic = incoming.topic.replace("reader-01", "unknown")
        else:
            payload = json.loads(incoming.payload)
            payload["antenna"] = 2
            incoming.payload = json.dumps(payload).encode()
        receiver._on_message(client, None, incoming)
        receiver._flush_pending()
        client.ack.assert_called_once_with(42, 1)
        assert not receiver.failed.is_set()
        audit = [json.loads(line) for line in path.read_text().splitlines()]
        assert audit[0]["payload_original"] == incoming.payload.decode()
        if kind == "invalid":
            assert len(audit) == 1
            assert audit[0]["canonical_event"] is None
            assert audit[0]["parse_error"]
        else:
            assert len(audit) == 2
            assert audit[1]["status"] == "rejected"
            assert audit[1]["reason"] == reason
        with pg_engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(LeituraBruta)) == 0


@pytest.mark.parametrize("append_number", [1, 2])
def test_audit_failure_never_acks(append_number):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        store = Mock()
        store.append.side_effect = [OSError("PRIVATE")] if append_number == 1 else [None, OSError("PRIVATE")]
        repository = Mock(persist=Mock(return_value=PersistenceResult("rejected", reason="unknown_reader")))
        receiver = MqttReceiver(Settings(), store, repository)
        receiver._on_message(factory.return_value, None, message())
        receiver._flush_pending()
        factory.return_value.ack.assert_not_called()
        assert receiver.failure == "persistência JSONL"
        if append_number == 1:
            repository.persist.assert_not_called()


def test_messages_after_failure_are_not_processed_or_acked(tmp_path):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        repository = Mock(persist=Mock(side_effect=PersistenceError("falha")))
        receiver = MqttReceiver(Settings(), JsonlEventStore(tmp_path / "audit.jsonl"), repository)
        for _ in range(2):
            receiver._on_message(factory.return_value, None, message())
            receiver._flush_pending()
        repository.persist.assert_called_once()
        factory.return_value.ack.assert_not_called()


def test_ack_send_failure_is_fatal(tmp_path):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        factory.return_value.ack.return_value = 2  # MQTT_ERR_PROTOCOL
        receiver = MqttReceiver(Settings(), JsonlEventStore(tmp_path / "audit.jsonl"),
                                Mock(persist=Mock(return_value=PersistenceResult("inserted", 1))))
        receiver._on_message(factory.return_value, None, message())
        receiver._flush_pending()
        assert receiver.failure == "envio de ACK"
        factory.return_value.ack.assert_called_once_with(42, 1)


def test_missing_app_url_fails_before_mqtt(monkeypatch, caplog):
    from rfid_ingestion.__main__ import main

    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    with patch("rfid_ingestion.__main__.MqttReceiver") as receiver:
        assert main() == 2
        receiver.assert_not_called()
    assert "APP_DATABASE_URL" in caplog.text


def _mensagem(mid, epc):
    return Mock(mid=mid, qos=1, retain=False,
                topic="easy/test/hupaa/portal-01/reader-01/readings",
                payload=json.dumps({"epc": epc, "antenna": 1, "rssi": -3880,
                                    "timestamp": "2026-09-01T13:00:00Z"}).encode())


class _RepositorioEmLote:
    def __init__(self, erro=None):
        self.lotes = []
        self.erro = erro

    def persist_many(self, envelopes):
        self.lotes.append([e["canonical_event"]["epc"] for e in envelopes])
        if self.erro:
            raise self.erro
        return [PersistenceResult("inserted") for _ in envelopes]

    def persist(self, envelope):  # pragma: no cover - não deve ser usado
        raise AssertionError("o receptor deve gravar em lote")


def test_mensagens_da_fila_sao_gravadas_num_lote_e_confirmadas_depois(tmp_path):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        client = factory.return_value
        client.ack.return_value = 0
        repository = _RepositorioEmLote()
        receiver = MqttReceiver(Settings(), JsonlEventStore(tmp_path / "a.jsonl"), repository)
        for mid in (1, 2, 3):
            receiver._on_message(client, None, _mensagem(mid, f"EPC-{mid}"))
        client.ack.assert_not_called()
        assert repository.lotes == []
        receiver._flush_pending()
    assert repository.lotes == [["EPC-1", "EPC-2", "EPC-3"]]
    assert [c.args for c in client.ack.call_args_list] == [(1, 1), (2, 1), (3, 1)]


def test_mensagem_de_sessao_anterior_nao_recebe_ack(tmp_path):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        client = factory.return_value
        client.ack.return_value = 0
        repository = _RepositorioEmLote()
        receiver = MqttReceiver(Settings(), JsonlEventStore(tmp_path / "a.jsonl"), repository)
        receiver._on_message(client, None, _mensagem(1, "EPC-1"))
        receiver._sessao += 1  # reconexão antes do processamento
        receiver._on_message(client, None, _mensagem(2, "EPC-2"))
        receiver._flush_pending()
    assert repository.lotes == [["EPC-2"]]
    assert [c.args for c in client.ack.call_args_list] == [(2, 1)]


def test_thread_de_processamento_grava_sem_o_loop_de_rede(tmp_path):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        client = factory.return_value
        client.ack.return_value = 0
        repository = _RepositorioEmLote()
        receiver = MqttReceiver(Settings(), JsonlEventStore(tmp_path / "a.jsonl"), repository)
        processor = Thread(target=receiver._processar)
        processor.start()
        try:
            for mid in (1, 2):
                receiver._on_message(client, None, _mensagem(mid, f"EPC-{mid}"))
            prazo = time.monotonic() + 5
            while client.ack.call_count < 2 and time.monotonic() < prazo:
                time.sleep(0.01)
        finally:
            receiver.shutdown.set()
            processor.join(timeout=5)
    assert sum(len(lote) for lote in repository.lotes) == 2
    assert client.ack.call_count == 2


def test_falha_temporaria_no_lote_nao_confirma_nenhuma_mensagem(tmp_path):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        repository = _RepositorioEmLote(PersistenceError("falha PostgreSQL"))
        receiver = MqttReceiver(Settings(), JsonlEventStore(tmp_path / "a.jsonl"), repository)
        for mid in (1, 2):
            receiver._on_message(factory.return_value, None, _mensagem(mid, f"EPC-{mid}"))
        receiver._flush_pending()
        factory.return_value.ack.assert_not_called()
        assert receiver.database_unavailable.is_set()
        assert not receiver.failed.is_set()
        factory.return_value.disconnect.assert_called_once()


def test_ack_apos_queda_da_conexao_fica_para_a_reentrega(tmp_path):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        factory.return_value.ack.return_value = 4
        receiver = MqttReceiver(Settings(), JsonlEventStore(tmp_path / "a.jsonl"),
                                _RepositorioEmLote())
        receiver._on_message(factory.return_value, None, _mensagem(1, "EPC-1"))
        receiver.disconnected.set()
        receiver._flush_pending()
        assert not receiver.failed.is_set()


def test_ack_sai_antes_da_inferencia_do_lote(tmp_path):
    ordem = []
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        client = factory.return_value
        client.ack.side_effect = lambda mid, qos: ordem.append(("ack", mid)) or 0
        receiver = MqttReceiver(Settings(), JsonlEventStore(tmp_path / "a.jsonl"),
                                _RepositorioEmLote())
        receiver._registrar_resultado = lambda event, result, chegada: ordem.append(
            ("inferencia", event["canonical_event"]["epc"]))
        receiver._inferencia = Mock()  # inferência em thread própria
        for mid in (1, 2):
            receiver._on_message(client, None, _mensagem(mid, f"EPC-{mid}"))
        receiver._flush_pending()
        while not receiver._fila_inferencia.empty():
            event, result, chegada = receiver._fila_inferencia.get()
            receiver._registrar_resultado(event, result, chegada)
    assert ordem == [("ack", 1), ("ack", 2), ("inferencia", "EPC-1"), ("inferencia", "EPC-2")]


def test_relogio_da_inferencia_nao_passa_da_leitura_pendente(tmp_path):
    relogio = [100.0]
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        client = factory.return_value
        client.ack.return_value = 0
        receiver = MqttReceiver(Settings(), JsonlEventStore(tmp_path / "a.jsonl"),
                                _RepositorioEmLote(), monotonic_clock=lambda: relogio[0])
        receiver._inferencia = Mock()
        receiver._on_message(client, None, _mensagem(1, "EPC-1"))
        relogio[0] = 101.0
        receiver._on_message(client, None, _mensagem(2, "EPC-2"))
        relogio[0] = 110.0  # inferência atrasada pelo banco remoto
        assert receiver.relogio_inferencia() == 100.0
        receiver._flush_pending()
        assert receiver.relogio_inferencia() == 100.0
        event, result, chegada = receiver._fila_inferencia.get()
        receiver._registrar_resultado(event, result, chegada)
        assert receiver.relogio_inferencia() == 101.0
        event, result, chegada = receiver._fila_inferencia.get()
        receiver._registrar_resultado(event, result, chegada)
        assert receiver.relogio_inferencia() == 110.0


def test_ack_sem_conexao_nao_derruba_o_ingestor(tmp_path):
    # Queda de conexão (ex.: TLS derrubado pelo broker) é temporária: o loop
    # reconecta e o broker reentrega a mensagem sem PUBACK.
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        factory.return_value.ack.return_value = 4  # MQTT_ERR_NO_CONN
        receiver = MqttReceiver(Settings(), JsonlEventStore(tmp_path / "a.jsonl"),
                                _RepositorioEmLote())
        receiver._on_message(factory.return_value, None, _mensagem(1, "EPC-1"))
        receiver._flush_pending()
        assert not receiver.failed.is_set()


def test_ack_de_outra_thread_e_enviado_pela_thread_de_rede(tmp_path):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        client = factory.return_value
        client.ack.return_value = 0
        client.connect.return_value = 0
        receiver = MqttReceiver(Settings(), JsonlEventStore(tmp_path / "a.jsonl"),
                                _RepositorioEmLote())
        rede = Thread(target=lambda: None)
        receiver._worker = rede  # finge a thread de rede viva
        rede.is_alive = lambda: True
        receiver._on_message(client, None, _mensagem(1, "EPC-1"))
        receiver._flush_pending()  # chamado fora da thread de rede
        client.ack.assert_not_called()
        receiver._worker = None
        receiver._enviar_acks()
        client.ack.assert_called_once_with(1, 1)


def test_desconexao_pedida_por_outra_thread_e_feita_pela_rede(tmp_path):
    with patch("rfid_ingestion.mqtt_client.create_client") as factory:
        client = factory.return_value
        client.connect.return_value = 0
        repository = _RepositorioEmLote(PersistenceError("falha PostgreSQL"))
        receiver = MqttReceiver(Settings(), JsonlEventStore(tmp_path / "a.jsonl"), repository)
        receiver._processor = Mock()
        receiver._worker = Mock(is_alive=lambda: True)
        receiver._on_message(client, None, _mensagem(1, "EPC-1"))
        receiver._flush_pending()
        client.disconnect.assert_not_called()
        assert receiver.database_unavailable.is_set()
        receiver._worker = None
        client.loop.return_value = 0
        receiver._network_session()
        client.disconnect.assert_called_once()
