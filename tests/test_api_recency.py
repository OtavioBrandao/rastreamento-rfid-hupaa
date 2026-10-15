"""Contrato HTTP da recência sem depender de banco ou relógio da máquina."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import router_equipamento
from api.database import get_db
from api.main import app
from rfid_location.recency import recency_threshold_from_env

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def equipment(id: int, detected_at: datetime | None):
    return SimpleNamespace(
        id=id, nome=f"Maca {id}", tipo_id=1, tipo=SimpleNamespace(nome="Maca"),
        identificador_interno=f"PAT-{id}",
        identificador_interno_normalizado=f"pat-{id}", descricao=None,
        status="ativo", ultima_zona_id=None, ultima_deteccao_em=detected_at, versao=1,
        created_at=NOW, updated_at=NOW,
    )


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[router_equipamento.get_recency_context] = (
        lambda: (NOW, recency_threshold_from_env())
    )
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_listagem_expoe_tres_estados_e_referencia_temporal(client, monkeypatch):
    deteccao_fuso = datetime(2026, 9, 23, 8, 30, tzinfo=timezone(timedelta(hours=-3)))
    items = [equipment(1, None), equipment(2, deteccao_fuso),
             equipment(3, NOW - timedelta(minutes=30, microseconds=1))]
    monkeypatch.setattr(
        router_equipamento.service, "listar",
        lambda *_args, **_kwargs: SimpleNamespace(
            items=items, page=1, size=20, total=3, pages=1
        ),
    )

    response = client.get("/equipamentos")

    assert response.status_code == 200
    result = response.json()["items"]
    assert [item["estado_recencia"] for item in result] == [
        "nunca_detectada", "recente", "desatualizada"
    ]
    assert result[0]["ultima_deteccao_em"] is None
    assert datetime.fromisoformat(result[1]["ultima_deteccao_em"]) == deteccao_fuso
    assert datetime.fromisoformat(result[2]["ultima_deteccao_em"]).utcoffset() is not None


def test_detalhe_respeita_threshold_configurado(client, monkeypatch):
    monkeypatch.setenv("RFID_RECENCY_THRESHOLD_MINUTES", "45")
    monkeypatch.setattr(
        router_equipamento.service, "buscar_por_id",
        lambda *_args: equipment(4, NOW - timedelta(minutes=40)),
    )

    response = client.get("/equipamentos/4")

    assert response.status_code == 200
    assert response.json()["estado_recencia"] == "recente"
    assert datetime.fromisoformat(response.json()["ultima_deteccao_em"]) == (
        NOW - timedelta(minutes=40)
    )


def test_estado_muda_com_relogio_sem_escrever_no_equipamento(client, monkeypatch):
    item = equipment(5, NOW - timedelta(minutes=29))
    monkeypatch.setattr(router_equipamento.service, "buscar_por_id", lambda *_args: item)

    assert client.get("/equipamentos/5").json()["estado_recencia"] == "recente"
    app.dependency_overrides[router_equipamento.get_recency_context] = (
        lambda: (NOW + timedelta(minutes=2), recency_threshold_from_env())
    )
    assert client.get("/equipamentos/5").json()["estado_recencia"] == "desatualizada"
    assert item.ultima_deteccao_em == NOW - timedelta(minutes=29)
