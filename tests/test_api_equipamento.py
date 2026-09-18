"""
Testes do contrato HTTP da ISS-008, via TestClient do FastAPI.

Aqui o alvo é o que o router promete para o cliente: status code, formato
do corpo (inclusive `tipo_nome`) e tradução das exceções de domínio. A
regra de negócio em si já está coberta em `tests/test_service_equipamento.py`.

Mesma fixture `client` do padrão da ISS-009: TestClient ligado ao
`engine` de teste via override de `get_db`, e `truncate_all` para limpar
o dado commitado de verdade entre testes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.database import get_db
from api.main import app


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


def _criar_tipo(client, nome: str = "Maca") -> dict:
    resposta = client.post("/tipos-equipamento", json={"nome": nome})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _criar_equipamento(
    client,
    tipo_id: int,
    nome: str = "Maca do 3o andar",
    identificador_interno: str = "PAT-0001",
    descricao: str | None = None,
) -> dict:
    corpo: dict[str, object] = {
        "nome": nome,
        "tipo_id": tipo_id,
        "identificador_interno": identificador_interno,
    }
    if descricao is not None:
        corpo["descricao"] = descricao
    resposta = client.post("/equipamentos", json=corpo)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def test_post_cria_e_devolve_201_com_tipo_nome(client):
    tipo = _criar_tipo(client, "Cadeira de rodas")

    resposta = client.post(
        "/equipamentos",
        json={
            "nome": "Cadeira 1",
            "tipo_id": tipo["id"],
            "identificador_interno": "PAT-0001",
            "descricao": "Cadeira manual",
        },
    )

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["nome"] == "Cadeira 1"
    assert corpo["tipo_id"] == tipo["id"]
    assert corpo["tipo_nome"] == "Cadeira de rodas"
    assert corpo["identificador_interno"] == "PAT-0001"
    assert corpo["identificador_interno_normalizado"] == "pat-0001"
    assert corpo["descricao"] == "Cadeira manual"
    assert corpo["status"] == "ativo"
    assert isinstance(corpo["id"], int)


def test_post_com_tipo_inexistente_devolve_422(client):
    resposta = client.post(
        "/equipamentos",
        json={"nome": "Maca", "tipo_id": 999999, "identificador_interno": "PAT-0002"},
    )

    assert resposta.status_code == 422


def test_post_com_tipo_inativo_devolve_422(client):
    tipo = _criar_tipo(client)
    client.post(f"/tipos-equipamento/{tipo['id']}/inativar")

    resposta = client.post(
        "/equipamentos",
        json={"nome": "Maca", "tipo_id": tipo["id"], "identificador_interno": "PAT-0003"},
    )

    assert resposta.status_code == 422


def test_post_com_identificador_duplicado_devolve_409(client):
    tipo = _criar_tipo(client)
    _criar_equipamento(client, tipo["id"], identificador_interno="PAT-0004")

    resposta = client.post(
        "/equipamentos",
        json={"nome": "Outra maca", "tipo_id": tipo["id"], "identificador_interno": "PAT-0004"},
    )

    assert resposta.status_code == 409


def test_post_com_identificador_duplicado_so_na_normalizacao_devolve_409(client):
    tipo = _criar_tipo(client)
    _criar_equipamento(client, tipo["id"], identificador_interno="PAT-0005")

    resposta = client.post(
        "/equipamentos",
        json={
            "nome": "Outra maca",
            "tipo_id": tipo["id"],
            "identificador_interno": "  pat-0005 ",
        },
    )

    assert resposta.status_code == 409


@pytest.mark.parametrize("nome_invalido", ["", "   "])
def test_post_com_nome_vazio_devolve_422(client, nome_invalido):
    tipo = _criar_tipo(client)

    resposta = client.post(
        "/equipamentos",
        json={
            "nome": nome_invalido,
            "tipo_id": tipo["id"],
            "identificador_interno": "PAT-0006",
        },
    )

    assert resposta.status_code == 422


def test_post_com_identificador_vazio_devolve_422(client):
    tipo = _criar_tipo(client)

    resposta = client.post(
        "/equipamentos",
        json={"nome": "Maca", "tipo_id": tipo["id"], "identificador_interno": "   "},
    )

    assert resposta.status_code == 422


def test_post_com_tipo_id_zero_ou_negativo_devolve_422(client):
    resposta = client.post(
        "/equipamentos",
        json={"nome": "Maca", "tipo_id": 0, "identificador_interno": "PAT-0007"},
    )

    assert resposta.status_code == 422


def test_get_lista_paginada(client):
    tipo = _criar_tipo(client)
    for indice in range(5):
        _criar_equipamento(client, tipo["id"], identificador_interno=f"PAT-{indice:04d}")

    resposta = client.get("/equipamentos", params={"page": 1, "size": 2})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["total"] == 5
    assert corpo["pages"] == 3
    assert len(corpo["items"]) == 2
    # Cada item já traz tipo_nome sem query extra do lado do cliente.
    assert all(item["tipo_nome"] == tipo["nome"] for item in corpo["items"])


def test_get_lista_esconde_inativos_por_padrao(client):
    tipo = _criar_tipo(client)
    criado = _criar_equipamento(client, tipo["id"], identificador_interno="PAT-0008")
    client.post(f"/equipamentos/{criado['id']}/inativar")

    padrao = client.get("/equipamentos").json()
    assert padrao["total"] == 0

    com_inativos = client.get("/equipamentos", params={"incluir_inativos": True}).json()
    assert com_inativos["total"] == 1


def test_get_por_id(client):
    tipo = _criar_tipo(client)
    criado = _criar_equipamento(client, tipo["id"], identificador_interno="PAT-0009")

    resposta = client.get(f"/equipamentos/{criado['id']}")

    assert resposta.status_code == 200
    assert resposta.json()["id"] == criado["id"]


def test_get_por_id_inexistente_devolve_404(client):
    resposta = client.get("/equipamentos/999999")

    assert resposta.status_code == 404


def test_patch_atualiza_nome_e_tipo(client):
    tipo_a = _criar_tipo(client, "Maca")
    tipo_b = _criar_tipo(client, "Cadeira de rodas")
    criado = _criar_equipamento(client, tipo_a["id"], identificador_interno="PAT-0010")

    resposta = client.patch(
        f"/equipamentos/{criado['id']}",
        json={"nome": "Maca renomeada", "tipo_id": tipo_b["id"]},
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["nome"] == "Maca renomeada"
    assert corpo["tipo_id"] == tipo_b["id"]
    assert corpo["tipo_nome"] == "Cadeira de rodas"


def test_patch_para_tipo_inativo_devolve_422(client):
    tipo_a = _criar_tipo(client, "Maca")
    tipo_b = _criar_tipo(client, "Cadeira de rodas")
    client.post(f"/tipos-equipamento/{tipo_b['id']}/inativar")
    criado = _criar_equipamento(client, tipo_a["id"], identificador_interno="PAT-0011")

    resposta = client.patch(f"/equipamentos/{criado['id']}", json={"tipo_id": tipo_b["id"]})

    assert resposta.status_code == 422
    # Sem efeito colateral: o tipo_id original continua valendo.
    assert client.get(f"/equipamentos/{criado['id']}").json()["tipo_id"] == tipo_a["id"]


def test_patch_nao_aceita_identificador_interno(client):
    """
    `identificador_interno` é imutável; o schema de update nem tem o
    campo, então mandá-lo no corpo é ignorado (não vira erro nem muda
    nada) — o Pydantic descarta o campo extra silenciosamente.
    """
    tipo = _criar_tipo(client)
    criado = _criar_equipamento(client, tipo["id"], identificador_interno="PAT-0012")

    resposta = client.patch(
        f"/equipamentos/{criado['id']}", json={"identificador_interno": "PAT-9999"}
    )

    assert resposta.status_code == 200
    assert resposta.json()["identificador_interno"] == "PAT-0012"


def test_patch_sem_descricao_no_corpo_preserva_a_atual(client):
    tipo = _criar_tipo(client)
    criado = _criar_equipamento(
        client, tipo["id"], identificador_interno="PAT-0013", descricao="descrição original"
    )

    resposta = client.patch(f"/equipamentos/{criado['id']}", json={"nome": "Maca renomeada"})

    assert resposta.status_code == 200
    assert resposta.json()["descricao"] == "descrição original"


def test_patch_com_descricao_nula_explicita_limpa_o_campo(client):
    tipo = _criar_tipo(client)
    criado = _criar_equipamento(
        client, tipo["id"], identificador_interno="PAT-0014", descricao="descrição original"
    )

    resposta = client.patch(f"/equipamentos/{criado['id']}", json={"descricao": None})

    assert resposta.status_code == 200
    assert resposta.json()["descricao"] is None


def test_patch_inexistente_devolve_404(client):
    tipo = _criar_tipo(client)

    resposta = client.patch(
        "/equipamentos/999999", json={"tipo_id": tipo["id"]}
    )

    assert resposta.status_code == 404


def test_inativar_devolve_200_e_status_inativo(client):
    tipo = _criar_tipo(client)
    criado = _criar_equipamento(client, tipo["id"], identificador_interno="PAT-0015")

    resposta = client.post(f"/equipamentos/{criado['id']}/inativar")

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "inativo"


def test_inativar_nao_apaga_a_linha(client):
    tipo = _criar_tipo(client)
    criado = _criar_equipamento(client, tipo["id"], identificador_interno="PAT-0016")

    client.post(f"/equipamentos/{criado['id']}/inativar")

    resposta = client.get(f"/equipamentos/{criado['id']}")
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "inativo"


def test_inativar_duas_vezes_devolve_200_as_duas(client):
    tipo = _criar_tipo(client)
    criado = _criar_equipamento(client, tipo["id"], identificador_interno="PAT-0017")

    primeira = client.post(f"/equipamentos/{criado['id']}/inativar")
    segunda = client.post(f"/equipamentos/{criado['id']}/inativar")

    assert primeira.status_code == 200
    assert segunda.status_code == 200
    assert segunda.json()["status"] == "inativo"


def test_inativar_inexistente_devolve_404(client):
    resposta = client.post("/equipamentos/999999/inativar")

    assert resposta.status_code == 404


def test_reativar_devolve_200_e_status_ativo(client):
    tipo = _criar_tipo(client)
    criado = _criar_equipamento(client, tipo["id"], identificador_interno="PAT-0018")
    client.post(f"/equipamentos/{criado['id']}/inativar")

    resposta = client.post(f"/equipamentos/{criado['id']}/reativar")

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "ativo"


def test_reativar_inexistente_devolve_404(client):
    resposta = client.post("/equipamentos/999999/reativar")

    assert resposta.status_code == 404
