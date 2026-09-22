"""
API integration tests for logical portal topology and antenna mappings (ISS-013).

Validates REST contract:
- POST   /portais/{portal_id}/mapeamentos
- GET    /portais/{portal_id}/mapeamentos
- GET    /portais/{portal_id}/topologia
- GET    /mapeamentos-antena/{mapeamento_id}
- PATCH  /mapeamentos-antena/{mapeamento_id}
- POST   /mapeamentos-antena/{mapeamento_id}/inativar
- GET    /antenas/{antena_id}/mapeamentos
- Hardware mutation guards (409 Conflict) when active mappings exist.
"""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.database import get_db
from api.main import app

_COUNTER = itertools.count(1)


@pytest.fixture
def client(engine, truncate_all):
    def get_db_de_teste():
        session = Session(bind=engine)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = get_db_de_teste
    try:
        with TestClient(app) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.clear()


def _serial() -> str:
    return str(next(_COUNTER))


def _criar_hierarquia_e_hardware(client):
    """Helper creating physical hierarchy and hardware via REST endpoints."""
    # 1. Andar, Setor, Zonas
    res_andar = client.post("/andares", json={"nome": f"Andar {_serial()}"})
    assert res_andar.status_code == 201
    andar_id = res_andar.json()["id"]

    res_setor = client.post("/setores", json={"andar_id": andar_id, "nome": f"Setor {_serial()}"})
    assert res_setor.status_code == 201
    setor_id = res_setor.json()["id"]

    res_za = client.post("/zonas", json={"setor_id": setor_id, "nome": f"Zona A {_serial()}"})
    res_zb = client.post("/zonas", json={"setor_id": setor_id, "nome": f"Zona B {_serial()}"})
    res_zc = client.post("/zonas", json={"setor_id": setor_id, "nome": f"Zona C {_serial()}"})
    assert res_za.status_code == 201 and res_zb.status_code == 201 and res_zc.status_code == 201
    zona_a = res_za.json()
    zona_b = res_zb.json()
    zona_c = res_zc.json()

    # 2. Leitor e Portal
    res_leitor = client.post(
        "/leitores",
        json={
            "reader_id": f"reader-{_serial()}",
            "fabricante": "Identix",
            "modelo": "EZ700",
            "identificador_serial": f"ser-{_serial()}",
        },
    )
    assert res_leitor.status_code == 201
    leitor = res_leitor.json()

    res_portal = client.post(
        "/portais",
        json={
            "nome": f"Portal {_serial()}",
            "zona_a_id": zona_a["id"],
            "zona_b_id": zona_b["id"],
        },
    )
    assert res_portal.status_code == 201
    portal = res_portal.json()

    # 3. Antenas
    res_antena_a = client.post(
        "/antenas",
        json={
            "leitor_id": leitor["id"],
            "porta_numero": 1,
            "zona_associada_id": zona_a["id"],
            "funcao": "entrada",
            "portal_id": portal["id"],
        },
    )
    res_antena_b = client.post(
        "/antenas",
        json={
            "leitor_id": leitor["id"],
            "porta_numero": 2,
            "zona_associada_id": zona_b["id"],
            "funcao": "saida",
            "portal_id": portal["id"],
        },
    )
    assert res_antena_a.status_code == 201 and res_antena_b.status_code == 201
    antena_a = res_antena_a.json()
    antena_b = res_antena_b.json()

    return zona_a, zona_b, zona_c, leitor, portal, antena_a, antena_b


def test_criar_e_consultar_mapeamento_api(client):
    zona_a, zona_b, _, leitor, portal, antena_a, antena_b = _criar_hierarquia_e_hardware(client)

    # 1. Create mapping on side A
    res_map_a = client.post(
        f"/portais/{portal['id']}/mapeamentos",
        json={"antena_id": antena_a["id"], "lado": "a", "funcao": "entrada"},
    )
    assert res_map_a.status_code == 201
    data_a = res_map_a.json()
    assert data_a["antena_id"] == antena_a["id"]
    assert data_a["portal_id"] == portal["id"]
    assert data_a["lado"] == "a"
    assert data_a["zona_id"] == zona_a["id"]
    assert data_a["funcao"] == "entrada"
    assert data_a["fim"] is None

    # 2. Create mapping on side B
    res_map_b = client.post(
        f"/portais/{portal['id']}/mapeamentos",
        json={"antena_id": antena_b["id"], "lado": "b", "funcao": "saida"},
    )
    assert res_map_b.status_code == 201
    data_b = res_map_b.json()
    assert data_b["lado"] == "b"
    assert data_b["zona_id"] == zona_b["id"]

    # 3. List portal mappings
    res_list = client.get(f"/portais/{portal['id']}/mapeamentos")
    assert res_list.status_code == 200
    itens = res_list.json()
    assert len(itens) == 2

    # 4. Detail single mapping
    res_det = client.get(f"/mapeamentos-antena/{data_a['id']}")
    assert res_det.status_code == 200
    assert res_det.json()["id"] == data_a["id"]


def test_obter_topologia_portal_completa_api(client):
    zona_a, zona_b, _, leitor, portal, antena_a, antena_b = _criar_hierarquia_e_hardware(client)

    client.post(
        f"/portais/{portal['id']}/mapeamentos",
        json={"antena_id": antena_a["id"], "lado": "a", "funcao": "entrada"},
    )
    client.post(
        f"/portais/{portal['id']}/mapeamentos",
        json={"antena_id": antena_b["id"], "lado": "b", "funcao": "saida"},
    )

    res = client.get(f"/portais/{portal['id']}/topologia")
    assert res.status_code == 200
    topo = res.json()
    assert topo["portal_id"] == portal["id"]
    assert topo["nome"] == portal["nome"]
    assert topo["zona_a"]["id"] == zona_a["id"]
    assert topo["zona_b"]["id"] == zona_b["id"]
    assert len(topo["antenas"]) == 2

    a1 = next(it for it in topo["antenas"] if it["lado"] == "a")
    assert a1["reader_id"] == leitor["reader_id"]
    assert a1["porta_numero"] == 1
    assert a1["zona_id"] == zona_a["id"]
    assert a1["funcao"] == "entrada"


def test_erros_validacao_criacao_mapeamento_api(client):
    zona_a, zona_b, zona_c, leitor, portal, antena_a, antena_b = _criar_hierarquia_e_hardware(client)

    # Incompatible third zone
    res_terceira = client.post(
        f"/portais/{portal['id']}/mapeamentos",
        json={
            "antena_id": antena_a["id"],
            "lado": "a",
            "funcao": "entrada",
            "zona_id": zona_c["id"],
        },
    )
    assert res_terceira.status_code == 422
    assert "não pertence ao lado 'A'" in res_terceira.json()["detail"]

    # Side/zone mismatch
    res_mismatch = client.post(
        f"/portais/{portal['id']}/mapeamentos",
        json={
            "antena_id": antena_a["id"],
            "lado": "a",
            "funcao": "entrada",
            "zona_id": zona_b["id"],
        },
    )
    assert res_mismatch.status_code == 422

    # Invalid side
    res_lado = client.post(
        f"/portais/{portal['id']}/mapeamentos",
        json={"antena_id": antena_a["id"], "lado": "x", "funcao": "entrada"},
    )
    assert res_lado.status_code == 422

    # Invalid function
    res_func = client.post(
        f"/portais/{portal['id']}/mapeamentos",
        json={"antena_id": antena_a["id"], "lado": "a", "funcao": "indefinido"},
    )
    assert res_func.status_code == 422

    # Duplicate active mapping
    client.post(
        f"/portais/{portal['id']}/mapeamentos",
        json={"antena_id": antena_a["id"], "lado": "a", "funcao": "entrada"},
    )
    res_dup = client.post(
        f"/portais/{portal['id']}/mapeamentos",
        json={"antena_id": antena_a["id"], "lado": "a", "funcao": "auxiliar"},
    )
    assert res_dup.status_code == 409

    # Inactive reader -> 422
    client.post(f"/leitores/{leitor['id']}/inativar")
    res_leitor_inativo = client.post(
        f"/portais/{portal['id']}/mapeamentos",
        json={"antena_id": antena_b["id"], "lado": "b", "funcao": "saida"},
    )
    assert res_leitor_inativo.status_code == 422
    assert "inativo" in res_leitor_inativo.json()["detail"]


def test_atualizacao_temporal_e_inativacao_api(client):
    zona_a, zona_b, _, leitor, portal, antena_a, _ = _criar_hierarquia_e_hardware(client)

    # 1. Create mapping
    res_create = client.post(
        f"/portais/{portal['id']}/mapeamentos",
        json={"antena_id": antena_a["id"], "lado": "a", "funcao": "entrada"},
    )
    m1 = res_create.json()

    # 2. Update mapping (temporal replacement)
    res_update = client.patch(
        f"/mapeamentos-antena/{m1['id']}",
        json={"funcao": "auxiliar"},
    )
    assert res_update.status_code == 200
    m2 = res_update.json()
    assert m2["id"] != m1["id"]
    assert m2["funcao"] == "auxiliar"
    assert m2["fim"] is None

    # Verify m1 is closed
    res_m1 = client.get(f"/mapeamentos-antena/{m1['id']}")
    assert res_m1.status_code == 200
    assert res_m1.json()["fim"] is not None

    # 3. Check antenna mapping history endpoint
    res_hist = client.get(f"/antenas/{antena_a['id']}/mapeamentos")
    assert res_hist.status_code == 200
    hist = res_hist.json()
    assert len(hist) == 2

    # 4. Inactivate m2
    res_inativar = client.post(f"/mapeamentos-antena/{m2['id']}/inativar")
    assert res_inativar.status_code == 200
    assert res_inativar.json()["fim"] is not None

    # 5. Check active topology is now empty
    res_topo = client.get(f"/portais/{portal['id']}/topologia")
    assert res_topo.status_code == 200
    assert len(res_topo.json()["antenas"]) == 0


def test_guards_bloqueio_mutacao_hardware_api(client):
    zona_a, zona_b, zona_c, leitor, portal, antena_a, _ = _criar_hierarquia_e_hardware(client)

    # Create active mapping
    res_map = client.post(
        f"/portais/{portal['id']}/mapeamentos",
        json={"antena_id": antena_a["id"], "lado": "a", "funcao": "entrada"},
    )
    assert res_map.status_code == 201
    map_id = res_map.json()["id"]

    # Attempt to change portal zone_a_id -> blocked with 409
    res_patch_portal = client.patch(
        f"/portais/{portal['id']}",
        json={"zona_a_id": zona_c["id"]},
    )
    assert res_patch_portal.status_code == 409
    assert "mapeamento(s) lógico(s) ativo(s)" in res_patch_portal.json()["detail"]

    # Attempt to detach antenna from portal -> blocked with 409
    res_patch_antena = client.patch(
        f"/antenas/{antena_a['id']}",
        json={"portal_id": None},
    )
    assert res_patch_antena.status_code == 409
    assert "possui mapeamento lógico ativo" in res_patch_antena.json()["detail"]

    # Attempt to inactivate portal with active mapping -> blocked with 409
    res_inat_portal = client.post(f"/portais/{portal['id']}/inativar")
    assert res_inat_portal.status_code == 409
    assert "mapeamento(s) lógico(s) ativo(s)" in res_inat_portal.json()["detail"]

    # Attempt to inactivate antenna with active mapping -> blocked with 409
    res_inat_antena = client.post(f"/antenas/{antena_a['id']}/inativar")
    assert res_inat_antena.status_code == 409
    assert "possui mapeamento lógico ativo" in res_inat_antena.json()["detail"]

    # Attempt to inactivate reader with active mapped antenna -> blocked with 409
    res_inat_leitor = client.post(f"/leitores/{leitor['id']}/inativar")
    assert res_inat_leitor.status_code == 409
    assert "mapeamento(s) lógico(s) ativo(s)" in res_inat_leitor.json()["detail"]

    # Inactivate the logical mapping (becomes historical)
    res_close = client.post(f"/mapeamentos-antena/{map_id}/inativar")
    assert res_close.status_code == 200

    # Historical mapping does not block inactivation
    assert client.post(f"/portais/{portal['id']}/inativar").status_code == 200
    assert client.post(f"/antenas/{antena_a['id']}/inativar").status_code == 200
    assert client.post(f"/leitores/{leitor['id']}/inativar").status_code == 200
