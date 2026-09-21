"""
Testes do contrato HTTP da ISS-012 (leitores, antenas, portais), via TestClient.

O alvo é o que o router promete: status code, formato do corpo e tradução das
exceções de domínio. A regra de negócio está em `tests/test_service_hardware.py`.
Mesma fixture `client` das issues anteriores (override de `get_db` + `truncate_all`).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.database import get_db
from api.main import app
from db.models import LeituraBruta, Passagem


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


_N = iter(range(1, 10_000))


def _ok(resposta, codigo=201):
    assert resposta.status_code == codigo, resposta.text
    return resposta.json()


def _zonas(client, quantas=2):
    andar = _ok(client.post("/andares", json={"nome": "4º Andar"}))
    setor = _ok(client.post("/setores", json={"andar_id": andar["id"], "nome": "Ala Norte"}))
    return [
        _ok(client.post("/zonas", json={"setor_id": setor["id"], "nome": f"Zona {i}"}))
        for i in range(quantas)
    ]


def _leitor(client, **extra):
    n = next(_N)
    corpo = {
        "reader_id": f"reader-{n:03d}",
        "fabricante": "Identix",
        "modelo": "EZ700",
        "identificador_serial": f"SN-{n:04d}",
        **extra,
    }
    return _ok(client.post("/leitores", json=corpo))


def _portal(client, zonas, nome="Portal 01"):
    return _ok(
        client.post("/portais", json={"nome": nome, "zona_a_id": zonas[0]["id"], "zona_b_id": zonas[1]["id"]})
    )


def _antena(client, leitor, zona, porta=1, funcao="entrada", portal=None):
    corpo = {
        "leitor_id": leitor["id"],
        "porta_numero": porta,
        "zona_associada_id": zona["id"],
        "funcao": funcao,
    }
    if portal is not None:
        corpo["portal_id"] = portal["id"]
    return _ok(client.post("/antenas", json=corpo))


# ================================== leitores ==================================


def test_post_leitor_devolve_201_com_cadastro_e_conectividade(client):
    corpo = _ok(
        client.post(
            "/leitores",
            json={
                "reader_id": "reader-01",
                "fabricante": "Identix",
                "modelo": "EZ700",
                "identificador_serial": "SN-0001",
                "endereco_rede": "192.168.0.10",
                "parametros_ingestao": {"adapter": "ez700", "qos": 1},
            },
        )
    )

    assert corpo["reader_id"] == "reader-01"
    assert corpo["identificador_serial"] == "SN-0001"  # campo distinto de reader_id
    assert corpo["parametros_ingestao"] == {"adapter": "ez700", "qos": 1}
    assert corpo["ativo"] is True
    assert corpo["status"] == "offline" and corpo["ultimo_heartbeat_em"] is None
    assert "portal_id" not in corpo  # a associação com portal mora na antena


def test_post_leitor_sem_parametros_devolve_null(client):
    assert _leitor(client)["parametros_ingestao"] is None


def test_post_leitor_com_reader_id_duplicado_devolve_409(client):
    _leitor(client, reader_id="reader-01")

    resposta = client.post(
        "/leitores",
        json={"reader_id": "reader-01", "fabricante": "X", "modelo": "Y", "identificador_serial": "OUTRO"},
    )

    assert resposta.status_code == 409 and "reader_id" in resposta.json()["detail"]


def test_post_leitor_com_serial_duplicado_devolve_409(client):
    _leitor(client, identificador_serial="SN-1")

    resposta = client.post(
        "/leitores",
        json={"reader_id": "outro", "fabricante": "X", "modelo": "Y", "identificador_serial": "SN-1"},
    )

    assert resposta.status_code == 409 and "identificador_serial" in resposta.json()["detail"]


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("reader_id", ""),
        ("reader_id", "reader 01"),
        ("reader_id", "reader/01"),
        ("fabricante", "  "),
        ("modelo", ""),
        ("identificador_serial", "   "),
    ],
)
def test_post_leitor_com_campo_invalido_devolve_422(client, campo, valor):
    corpo = {"reader_id": "r1", "fabricante": "X", "modelo": "Y", "identificador_serial": "S1", campo: valor}

    assert client.post("/leitores", json=corpo).status_code == 422


def test_post_leitor_sem_campo_obrigatorio_devolve_422(client):
    assert client.post("/leitores", json={"fabricante": "X", "modelo": "Y"}).status_code == 422


# --- parametros_ingestao: ALLOWLIST fechada (422 para qualquer chave fora dela) --------------


def _post_leitor(client, parametros):
    return client.post(
        "/leitores",
        json={
            "reader_id": "reader-01",
            "fabricante": "Identix",
            "modelo": "EZ700",
            "identificador_serial": "SN-0001",
            "parametros_ingestao": parametros,
        },
    )


def test_post_leitor_aceita_todas_as_chaves_da_allowlist(client):
    parametros = {
        "protocolo": "mqtt",
        "adapter": "ez700",
        "formato_timestamp": "epoch_ms",
        "topico": "easy/dev/hupaa/portal-01/reader-01/readings",
        "qos": 1,
    }

    corpo = _ok(_post_leitor(client, parametros))

    assert corpo["parametros_ingestao"] == parametros


@pytest.mark.parametrize(
    "parametros",
    [
        # a brecha da blocklist: segredo sob chave inocente
        {"x": "hunter2"},
        # chave INÓCUA mas não listada: é allowlist, não uma blocklist maior
        {"descricao": "leitor do corredor"},
        # credenciais óbvias
        {"password": "hunter2"},
        {"senha": "hunter2"},
        {"mqtt": {"username": "u", "password": "hunter2"}},
        {"broker_url": "mqtt://usuario:hunter2@broker.local:1883"},
        {"token": "hunter2"},
        # chave permitida com um valor que tenta carregar credencial
        {"topico": "mqtt://usuario:hunter2@broker.local/easy/dev/hupaa/p/r/readings"},
        {"adapter": "hunter2 com espaço"},
    ],
)
def test_post_leitor_com_parametros_fora_da_allowlist_devolve_422(client, parametros):
    resposta = _post_leitor(client, parametros)

    assert resposta.status_code == 422
    assert "parametros_ingestao" in resposta.text
    # rejeitar SEM ecoar: o segredo enviado não volta no corpo da resposta
    assert "hunter2" not in resposta.text
    # e nada foi gravado
    assert client.get("/leitores", params={"incluir_inativos": True}).json()["total"] == 0


def test_post_leitor_com_chave_inocua_fora_da_allowlist_devolve_422_com_a_lista(client):
    resposta = _post_leitor(client, {"descricao": "leitor do corredor"})

    assert resposta.status_code == 422
    assert "allowlist" in resposta.text
    for chave in ("adapter", "formato_timestamp", "protocolo", "qos", "topico"):
        assert chave in resposta.text  # o cliente descobre o que PODE mandar


def test_patch_leitor_com_parametros_fora_da_allowlist_devolve_422(client):
    leitor = _leitor(client, parametros_ingestao={"adapter": "ez700"})

    for parametros in ({"x": "hunter2"}, {"password": "hunter2"}, {"descricao": "x"}):
        resposta = client.patch(f"/leitores/{leitor['id']}", json={"parametros_ingestao": parametros})
        assert resposta.status_code == 422, parametros
        assert "hunter2" not in resposta.text
    # o valor anterior (legítimo) segue intacto
    assert client.get(f"/leitores/{leitor['id']}").json()["parametros_ingestao"] == {"adapter": "ez700"}


def test_patch_leitor_aceita_parametros_da_allowlist_e_null_para_limpar(client):
    leitor = _leitor(client)

    assert _ok(client.patch(f"/leitores/{leitor['id']}", json={"parametros_ingestao": {"qos": 1}}), 200)[
        "parametros_ingestao"
    ] == {"qos": 1}
    assert _ok(client.patch(f"/leitores/{leitor['id']}", json={"parametros_ingestao": None}), 200)[
        "parametros_ingestao"
    ] is None


def test_erros_de_validacao_de_outros_campos_continuam_ecoando_o_input_padrao(client):
    """O handler só poda `parametros_ingestao`; o 422 padrão do FastAPI segue igual no resto."""
    resposta = client.post("/leitores", json={"reader_id": "reader 01", "fabricante": "X", "modelo": "Y", "identificador_serial": "S"})

    assert resposta.status_code == 422
    assert any("input" in erro for erro in resposta.json()["detail"])


# --- GET / PATCH ----------------------------------------------------------------------------------


def test_get_leitor_por_id_e_404(client):
    leitor = _leitor(client)

    assert client.get(f"/leitores/{leitor['id']}").json()["id"] == leitor["id"]
    assert client.get("/leitores/999999").status_code == 404


def test_patch_leitor_atualiza_so_o_informado(client):
    leitor = _leitor(client, endereco_rede="10.0.0.1")

    corpo = _ok(client.patch(f"/leitores/{leitor['id']}", json={"modelo": "EZ800"}), 200)

    assert corpo["modelo"] == "EZ800"
    assert corpo["fabricante"] == "Identix" and corpo["endereco_rede"] == "10.0.0.1"


def test_patch_leitor_com_null_limpa_os_campos_anulaveis(client):
    leitor = _leitor(client, endereco_rede="10.0.0.1", parametros_ingestao={"qos": 1})

    corpo = _ok(
        client.patch(f"/leitores/{leitor['id']}", json={"endereco_rede": None, "parametros_ingestao": None}),
        200,
    )

    assert corpo["endereco_rede"] is None and corpo["parametros_ingestao"] is None


def test_patch_leitor_com_null_em_coluna_not_null_devolve_422(client):
    leitor = _leitor(client)

    assert client.patch(f"/leitores/{leitor['id']}", json={"fabricante": None}).status_code == 422
    assert client.patch(f"/leitores/{leitor['id']}", json={"reader_id": None}).status_code == 422


def test_patch_leitor_ignora_status_e_heartbeat(client):
    """Conectividade ao vivo é da ingestão: o CRUD só expõe para leitura."""
    leitor = _leitor(client)

    corpo = _ok(
        client.patch(
            f"/leitores/{leitor['id']}",
            json={"status": "online", "ultimo_heartbeat_em": "2026-01-01T00:00:00Z", "modelo": "EZ800"},
        ),
        200,
    )

    assert corpo["status"] == "offline" and corpo["ultimo_heartbeat_em"] is None
    assert corpo["modelo"] == "EZ800"  # o resto do mesmo corpo foi aplicado


def test_patch_leitor_ativo_no_corpo_e_ignorado(client):
    """`ativo` só muda por inativar/reativar."""
    leitor = _leitor(client)

    assert _ok(client.patch(f"/leitores/{leitor['id']}", json={"ativo": False}), 200)["ativo"] is True


def test_patch_leitor_para_reader_id_ja_usado_devolve_409(client):
    _leitor(client, reader_id="reader-01")
    outro = _leitor(client, reader_id="reader-02")

    assert client.patch(f"/leitores/{outro['id']}", json={"reader_id": "reader-01"}).status_code == 409


def test_patch_leitor_inexistente_devolve_404(client):
    assert client.patch("/leitores/999999", json={"modelo": "X"}).status_code == 404


def test_lista_de_leitores_pagina_e_esconde_inativos(client):
    leitores = [_leitor(client) for _ in range(5)]
    client.post(f"/leitores/{leitores[0]['id']}/inativar")

    pagina = client.get("/leitores", params={"size": 2}).json()
    assert (pagina["total"], pagina["pages"], len(pagina["items"])) == (4, 2, 2)
    assert client.get("/leitores", params={"incluir_inativos": True}).json()["total"] == 5
    assert client.get("/leitores", params={"size": 101}).status_code == 422


# ================================== portais ==================================


def test_post_portal_devolve_201(client):
    zonas = _zonas(client)

    corpo = _ok(
        client.post(
            "/portais",
            json={"nome": "Portal Norte", "zona_a_id": zonas[0]["id"], "zona_b_id": zonas[1]["id"], "localizacao_fisica": "Hall"},
        )
    )

    assert (corpo["nome"], corpo["localizacao_fisica"], corpo["ativo"]) == ("Portal Norte", "Hall", True)
    assert "leitores" not in corpo


@pytest.mark.parametrize("lado", ["zona_a_id", "zona_b_id"])
def test_post_portal_com_zona_inexistente_devolve_422(client, lado):
    zonas = _zonas(client)
    ids = {"zona_a_id": zonas[0]["id"], "zona_b_id": zonas[1]["id"], lado: 999999}

    resposta = client.post("/portais", json={"nome": "P", **ids})

    assert resposta.status_code == 422 and lado in resposta.json()["detail"]


def test_post_portal_com_zona_inativa_devolve_422(client):
    zonas = _zonas(client)
    client.post(f"/zonas/{zonas[1]['id']}/inativar")

    resposta = client.post("/portais", json={"nome": "P", "zona_a_id": zonas[0]["id"], "zona_b_id": zonas[1]["id"]})

    assert resposta.status_code == 422 and "inativa" in resposta.json()["detail"]


def test_post_portal_com_zonas_iguais_devolve_422_e_nao_500(client):
    """O CHECK do banco vira 422 (exceção de domínio), não um erro genérico."""
    zonas = _zonas(client)

    resposta = client.post("/portais", json={"nome": "P", "zona_a_id": zonas[0]["id"], "zona_b_id": zonas[0]["id"]})

    assert resposta.status_code == 422 and "distintas" in resposta.json()["detail"]


def test_post_portal_com_nome_vazio_ou_id_invalido_devolve_422(client):
    zonas = _zonas(client)

    assert client.post("/portais", json={"nome": "  ", "zona_a_id": zonas[0]["id"], "zona_b_id": zonas[1]["id"]}).status_code == 422
    assert client.post("/portais", json={"nome": "P", "zona_a_id": 0, "zona_b_id": zonas[1]["id"]}).status_code == 422


def test_get_e_patch_de_portal(client):
    zonas = _zonas(client, 3)
    portal = _portal(client, zonas[:2])

    assert client.get(f"/portais/{portal['id']}").json()["id"] == portal["id"]
    assert client.get("/portais/999999").status_code == 404

    corpo = _ok(client.patch(f"/portais/{portal['id']}", json={"nome": "Sul", "zona_b_id": zonas[2]["id"]}), 200)
    assert (corpo["nome"], corpo["zona_b_id"]) == ("Sul", zonas[2]["id"])
    assert client.patch("/portais/999999", json={"nome": "X"}).status_code == 404


def test_patch_portal_com_zona_inativa_ou_igual_devolve_422(client):
    zonas = _zonas(client, 3)
    portal = _portal(client, zonas[:2])
    client.post(f"/zonas/{zonas[2]['id']}/inativar")

    assert client.patch(f"/portais/{portal['id']}", json={"zona_b_id": zonas[2]["id"]}).status_code == 422
    assert client.patch(f"/portais/{portal['id']}", json={"zona_a_id": zonas[1]["id"]}).status_code == 422
    assert client.patch(f"/portais/{portal['id']}", json={"nome": None}).status_code == 422


# ================================== antenas ==================================


def test_post_antena_devolve_201_com_e_sem_portal(client):
    zonas = _zonas(client)
    portal = _portal(client, zonas)
    leitor = _leitor(client)

    solta = _antena(client, leitor, zonas[0], porta=1)
    instalada = _antena(client, leitor, zonas[1], porta=2, portal=portal)

    assert solta["portal_id"] is None and solta["ativo"] is True
    assert instalada["portal_id"] == portal["id"]


def test_post_antena_com_leitor_inexistente_ou_inativo_devolve_422(client):
    zona = _zonas(client)[0]
    leitor = _leitor(client)
    corpo = {"porta_numero": 1, "zona_associada_id": zona["id"], "funcao": "entrada"}

    assert client.post("/antenas", json={**corpo, "leitor_id": 999999}).status_code == 422
    client.post(f"/leitores/{leitor['id']}/inativar")
    resposta = client.post("/antenas", json={**corpo, "leitor_id": leitor["id"]})
    assert resposta.status_code == 422 and "inativo" in resposta.json()["detail"]


def test_post_antena_com_zona_inexistente_ou_inativa_devolve_422(client):
    zonas = _zonas(client, 3)
    leitor = _leitor(client)
    corpo = {"leitor_id": leitor["id"], "porta_numero": 1, "funcao": "entrada"}

    assert client.post("/antenas", json={**corpo, "zona_associada_id": 999999}).status_code == 422
    client.post(f"/zonas/{zonas[2]['id']}/inativar")
    assert client.post("/antenas", json={**corpo, "zona_associada_id": zonas[2]["id"]}).status_code == 422


def test_post_antena_com_portal_inexistente_ou_inativo_devolve_422(client):
    zonas = _zonas(client)
    portal = _portal(client, zonas)
    leitor = _leitor(client)
    corpo = {"leitor_id": leitor["id"], "porta_numero": 1, "zona_associada_id": zonas[0]["id"], "funcao": "entrada"}

    assert client.post("/antenas", json={**corpo, "portal_id": 999999}).status_code == 422
    client.post(f"/portais/{portal['id']}/inativar")
    resposta = client.post("/antenas", json={**corpo, "portal_id": portal["id"]})
    assert resposta.status_code == 422 and "inativo" in resposta.json()["detail"]


def test_post_antena_com_porta_repetida_no_leitor_devolve_409(client):
    zonas = _zonas(client)
    leitor = _leitor(client)
    _antena(client, leitor, zonas[0], porta=1)

    resposta = client.post(
        "/antenas",
        json={"leitor_id": leitor["id"], "porta_numero": 1, "zona_associada_id": zonas[1]["id"], "funcao": "saida"},
    )

    assert resposta.status_code == 409


def test_post_antena_com_payload_invalido_devolve_422(client):
    zona = _zonas(client)[0]
    leitor = _leitor(client)
    base = {"leitor_id": leitor["id"], "porta_numero": 1, "zona_associada_id": zona["id"], "funcao": "entrada"}

    for invalido in ({"funcao": "lateral"}, {"porta_numero": 0}, {"leitor_id": 0}, {"portal_id": 0}):
        assert client.post("/antenas", json={**base, **invalido}).status_code == 422, invalido


def test_get_antena_por_id_e_404(client):
    zona = _zonas(client)[0]
    antena = _antena(client, _leitor(client), zona)

    assert client.get(f"/antenas/{antena['id']}").json()["id"] == antena["id"]
    assert client.get("/antenas/999999").status_code == 404


def test_patch_antena_atualiza_campos_e_desassocia_portal_com_null(client):
    zonas = _zonas(client)
    portal = _portal(client, zonas)
    antena = _antena(client, _leitor(client), zonas[0], portal=portal)

    corpo = _ok(client.patch(f"/antenas/{antena['id']}", json={"funcao": "saida", "porta_numero": 4}), 200)
    assert (corpo["funcao"], corpo["porta_numero"], corpo["portal_id"]) == ("saida", 4, portal["id"])  # portal preservado

    assert _ok(client.patch(f"/antenas/{antena['id']}", json={"portal_id": None}), 200)["portal_id"] is None
    assert _ok(client.patch(f"/antenas/{antena['id']}", json={"portal_id": portal["id"]}), 200)["portal_id"] == portal["id"]


def test_patch_antena_ignora_leitor_id_no_corpo(client):
    """Antena é fisicamente cabeada no leitor: `leitor_id` no PATCH não dá erro e não tem efeito."""
    zona = _zonas(client)[0]
    a, b = _leitor(client), _leitor(client)
    antena = _antena(client, a, zona)

    resposta = client.patch(f"/antenas/{antena['id']}", json={"leitor_id": b["id"], "funcao": "saida"})

    corpo = _ok(resposta, 200)
    assert corpo["leitor_id"] == a["id"]  # não trocou de leitor
    assert corpo["funcao"] == "saida"  # o resto do corpo foi aplicado
    assert client.get(f"/antenas/{antena['id']}").json()["leitor_id"] == a["id"]


def test_patch_antena_com_portal_ou_zona_invalidos_devolve_422_e_nada_muda(client):
    zonas = _zonas(client, 3)
    portal = _portal(client, zonas[:2])
    antena = _antena(client, _leitor(client), zonas[0])
    client.post(f"/zonas/{zonas[2]['id']}/inativar")
    client.post(f"/portais/{portal['id']}/inativar")

    assert client.patch(f"/antenas/{antena['id']}", json={"portal_id": portal["id"]}).status_code == 422
    assert client.patch(f"/antenas/{antena['id']}", json={"portal_id": 999999}).status_code == 422
    assert client.patch(f"/antenas/{antena['id']}", json={"zona_associada_id": zonas[2]["id"]}).status_code == 422
    assert client.get(f"/antenas/{antena['id']}").json()["portal_id"] is None


def test_patch_antena_para_porta_ja_usada_devolve_409(client):
    zona = _zonas(client)[0]
    leitor = _leitor(client)
    _antena(client, leitor, zona, porta=1)
    outra = _antena(client, leitor, zona, porta=2)

    assert client.patch(f"/antenas/{outra['id']}", json={"porta_numero": 1}).status_code == 409


def test_patch_antena_com_null_em_not_null_devolve_422(client):
    zona = _zonas(client)[0]
    antena = _antena(client, _leitor(client), zona)

    for campo in ("funcao", "porta_numero", "zona_associada_id"):
        assert client.patch(f"/antenas/{antena['id']}", json={campo: None}).status_code == 422, campo


def test_patch_antena_inexistente_devolve_404(client):
    assert client.patch("/antenas/999999", json={"funcao": "saida"}).status_code == 404


# ------------------------------ as duas topologias obrigatórias ------------------------------


def test_topologia_1_um_leitor_com_varias_antenas_em_portas_diferentes(client):
    zonas = _zonas(client, 4)
    leitor = _leitor(client)
    for indice, funcao in enumerate(("entrada", "saida", "entrada", "indefinido")):
        _antena(client, leitor, zonas[indice], porta=indice + 1, funcao=funcao)

    itens = client.get("/antenas", params={"leitor_id": leitor["id"]}).json()["items"]

    assert [a["porta_numero"] for a in itens] == [1, 2, 3, 4]
    assert {a["leitor_id"] for a in itens} == {leitor["id"]}


def test_topologia_2_um_portal_composto_por_antenas_de_leitores_distintos(client):
    zonas = _zonas(client)
    portal = _portal(client, zonas)
    leitor_a, leitor_b = _leitor(client), _leitor(client)
    entrada = _antena(client, leitor_a, zonas[0], porta=1, funcao="entrada", portal=portal)
    saida = _antena(client, leitor_b, zonas[1], porta=1, funcao="saida", portal=portal)

    itens = client.get("/antenas", params={"portal_id": portal["id"]}).json()["items"]

    assert {a["id"] for a in itens} == {entrada["id"], saida["id"]}
    assert {a["leitor_id"] for a in itens} == {leitor_a["id"], leitor_b["id"]}  # leitores DISTINTOS
    assert {a["portal_id"] for a in itens} == {portal["id"]}


def test_lista_de_antenas_esconde_inativas_e_valida_filtros(client):
    zonas = _zonas(client)
    portal = _portal(client, zonas)
    antena = _antena(client, _leitor(client), zonas[0], portal=portal)
    client.post(f"/antenas/{antena['id']}/inativar")

    assert client.get("/antenas", params={"portal_id": portal["id"]}).json()["total"] == 0
    assert client.get("/antenas", params={"portal_id": portal["id"], "incluir_inativos": True}).json()["total"] == 1
    assert client.get("/antenas", params={"leitor_id": 0}).status_code == 422


# ================= inativar NÃO é bloqueado por histórico (diferente da ISS-011) =================


def _historico(engine, antena_id, portal_id):
    with Session(bind=engine) as sessao:
        leitura = LeituraBruta(
            event_id=uuid.uuid4(),
            antena_id=antena_id,
            epc="AABBCCDD",
            rssi=Decimal("-55"),
            lido_em=datetime.now(timezone.utc),
        )
        sessao.add(leitura)
        sessao.flush()
        sessao.add(
            Passagem(
                epc="AABBCCDD",
                portal_id=portal_id,
                antena_origem_id=antena_id,
                leitura_origem_id=leitura.id,
                detectada_em=datetime.now(timezone.utc),
            )
        )
        sessao.commit()


def test_inativar_leitor_antena_e_portal_com_historico_devolve_200(client, engine):
    """
    Regra DELIBERADAMENTE diferente da ISS-011: `POST /zonas/{id}/inativar` devolve
    409 para zona referenciada; aqui nada bloqueia — o hardware inativo continua
    referenciado por leituras_brutas/passagens.
    """
    zonas = _zonas(client)
    portal = _portal(client, zonas)
    leitor = _leitor(client)
    antena = _antena(client, leitor, zonas[0], portal=portal)
    _historico(engine, antena["id"], portal["id"])

    for caminho in (
        f"/antenas/{antena['id']}/inativar",
        f"/portais/{portal['id']}/inativar",
        f"/leitores/{leitor['id']}/inativar",
    ):
        resposta = client.post(caminho)
        assert resposta.status_code == 200, (caminho, resposta.text)
        assert resposta.json()["ativo"] is False

    # a linha continua existindo e continua resolvendo
    assert client.get(f"/antenas/{antena['id']}").json()["ativo"] is False
    # ...e o contraste: a zona referenciada por esse hardware continua BLOQUEADA
    assert client.post(f"/zonas/{zonas[0]['id']}/inativar").status_code == 409


@pytest.mark.parametrize("recurso", ["leitores", "antenas", "portais"])
def test_inativar_e_reativar_inexistente_devolvem_404(client, recurso):
    assert client.post(f"/{recurso}/999999/inativar").status_code == 404
    assert client.post(f"/{recurso}/999999/reativar").status_code == 404


def test_inativar_e_reativar_sao_idempotentes_nos_tres_recursos(client):
    zonas = _zonas(client)
    leitor = _leitor(client)
    portal = _portal(client, zonas)
    antena = _antena(client, leitor, zonas[0])

    for recurso, item in (("leitores", leitor), ("portais", portal), ("antenas", antena)):
        for _ in range(2):
            assert client.post(f"/{recurso}/{item['id']}/inativar").json()["ativo"] is False
        for _ in range(2):
            assert client.post(f"/{recurso}/{item['id']}/reativar").json()["ativo"] is True


def test_lista_de_portais_pagina_e_esconde_inativos(client):
    zonas = _zonas(client)
    portais = [_portal(client, zonas, nome=f"P{i}") for i in range(3)]
    client.post(f"/portais/{portais[0]['id']}/inativar")

    assert client.get("/portais").json()["total"] == 2
    assert client.get("/portais", params={"incluir_inativos": True}).json()["total"] == 3


# ================= porta do leitor: só a antena ATIVA ocupa (índice único parcial) =================


def test_antena_inativada_libera_a_porta_para_uma_antena_nova_via_http(client):
    zona = _zonas(client)[0]
    leitor = _leitor(client)
    antiga = _antena(client, leitor, zona, porta=1)
    assert client.post(f"/antenas/{antiga['id']}/inativar").status_code == 200

    nova = _antena(client, leitor, zona, porta=1, funcao="saida")  # 201: não levanta

    assert nova["id"] != antiga["id"] and nova["ativo"] is True
    assert client.get(f"/antenas/{antiga['id']}").json()["ativo"] is False  # linha antiga preservada
    todas = client.get("/antenas", params={"leitor_id": leitor["id"], "incluir_inativos": True}).json()
    assert sorted(a["ativo"] for a in todas["items"]) == [False, True]
    # listagem padrão só mostra a ativa
    assert [a["id"] for a in client.get("/antenas", params={"leitor_id": leitor["id"]}).json()["items"]] == [nova["id"]]


def test_porta_repetida_entre_antenas_ativas_continua_409(client):
    zona = _zonas(client)[0]
    leitor = _leitor(client)
    _antena(client, leitor, zona, porta=1)

    resposta = client.post(
        "/antenas",
        json={"leitor_id": leitor["id"], "porta_numero": 1, "zona_associada_id": zona["id"], "funcao": "saida"},
    )

    assert resposta.status_code == 409 and "ATIVA" in resposta.json()["detail"]


def test_reativar_antena_cuja_porta_foi_tomada_devolve_409_e_nada_muda(client):
    zona = _zonas(client)[0]
    leitor = _leitor(client)
    antiga = _antena(client, leitor, zona, porta=1)
    client.post(f"/antenas/{antiga['id']}/inativar")
    nova = _antena(client, leitor, zona, porta=1)

    resposta = client.post(f"/antenas/{antiga['id']}/reativar")

    assert resposta.status_code == 409  # não 500: a colisão do índice foi traduzida
    assert client.get(f"/antenas/{antiga['id']}").json()["ativo"] is False
    # libera a porta e aí a reativação funciona
    client.post(f"/antenas/{nova['id']}/inativar")
    assert client.post(f"/antenas/{antiga['id']}/reativar").status_code == 200


def test_patch_de_antena_inativa_para_porta_ocupada_so_falha_ao_reativar(client):
    zona = _zonas(client)[0]
    leitor = _leitor(client)
    _antena(client, leitor, zona, porta=1)
    outra = _antena(client, leitor, zona, porta=2)
    client.post(f"/antenas/{outra['id']}/inativar")

    assert client.patch(f"/antenas/{outra['id']}", json={"porta_numero": 1}).status_code == 200
    assert client.post(f"/antenas/{outra['id']}/reativar").status_code == 409


# ================================== created_at / updated_at ==================================


@pytest.mark.parametrize("recurso", ["leitor", "portal", "antena"])
def test_respostas_expoem_created_at_e_updated_at(client, recurso):
    zonas = _zonas(client)
    criado = {
        "leitor": lambda: _leitor(client),
        "portal": lambda: _portal(client, zonas),
        "antena": lambda: _antena(client, _leitor(client), zonas[0]),
    }[recurso]()

    assert criado["created_at"] and criado["updated_at"]
    assert datetime.fromisoformat(criado["created_at"]).tzinfo is not None  # com fuso
    plural = {"leitor": "leitores", "portal": "portais", "antena": "antenas"}[recurso]
    assert client.get(f"/{plural}/{criado['id']}").json()["created_at"] == criado["created_at"]
    assert client.get(f"/{plural}").json()["items"][0]["created_at"] == criado["created_at"]


def _instante(texto: str) -> datetime:
    return datetime.fromisoformat(texto)


def test_patch_e_inativar_avancam_updated_at_sem_mexer_no_created_at(client):
    """
    Verificado por HTTP porque, na fixture `db`, o `now()` do Postgres é o instante
    de INÍCIO da transação e não avançaria entre operações do mesmo teste.
    """
    zonas = _zonas(client)
    casos = [
        ("leitores", _leitor(client), {"modelo": "EZ800"}),
        ("portais", _portal(client, zonas), {"nome": "Novo nome"}),
        ("antenas", _antena(client, _leitor(client), zonas[0]), {"funcao": "saida"}),
    ]

    for recurso, criado, mudanca in casos:
        depois_do_patch = client.patch(f"/{recurso}/{criado['id']}", json=mudanca).json()
        assert depois_do_patch["created_at"] == criado["created_at"], recurso
        assert _instante(depois_do_patch["updated_at"]) > _instante(criado["updated_at"]), recurso

        depois_de_inativar = client.post(f"/{recurso}/{criado['id']}/inativar").json()
        assert _instante(depois_de_inativar["updated_at"]) > _instante(depois_do_patch["updated_at"]), recurso
        assert depois_de_inativar["created_at"] == criado["created_at"], recurso


def test_operacao_idempotente_nao_mexe_no_updated_at(client):
    """Inativar quem já está inativo é no-op: não faz UPDATE, então não avança `updated_at`."""
    leitor = _leitor(client)
    primeira = client.post(f"/leitores/{leitor['id']}/inativar").json()

    segunda = client.post(f"/leitores/{leitor['id']}/inativar").json()

    assert segunda["updated_at"] == primeira["updated_at"]
