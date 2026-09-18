"""
Testes do contrato HTTP da ISS-009, via TestClient do FastAPI.

Aqui o alvo é o que o router promete para o cliente: status code, formato
do corpo e tradução das exceções de domínio. A regra de negócio em si já
está coberta em `tests/test_service_tipos_equipamento.py`.

Estes testes usam a fixture `truncate_all` (dado commitado de verdade),
não a `db`: o TestClient roda a dependency `get_db` da aplicação, que
abre a própria sessão e não enxerga a transação da fixture `db`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.database import get_db
from api.main import app
from db.models import Equipamento


@pytest.fixture
def client(engine, truncate_all):
    """
    TestClient ligado ao MESMO banco das outras fixtures.

    A dependency é sobrescrita para usar o `engine` do teste em vez do
    engine global da aplicação — assim o teste não depende de a
    DATABASE_URL do processo ser exatamente a mesma TEST_DATABASE_URL.
    """

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


def _criar(client, nome: str, descricao: str | None = None):
    corpo: dict[str, object] = {"nome": nome}
    if descricao is not None:
        corpo["descricao"] = descricao
    return client.post("/tipos-equipamento", json=corpo)


def test_health(client):
    resposta = client.get("/health")

    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


def test_post_cria_e_devolve_201(client):
    resposta = _criar(client, "Cadeira de rodas", "Cadeira manual")

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["nome"] == "Cadeira de rodas"
    assert corpo["nome_normalizado"] == "cadeira de rodas"
    assert corpo["descricao"] == "Cadeira manual"
    assert corpo["ativo"] is True
    assert isinstance(corpo["id"], int)


def test_post_com_nome_duplicado_devolve_409(client):
    _criar(client, "Maca")

    resposta = _criar(client, "Maca")

    assert resposta.status_code == 409


def test_post_com_nome_duplicado_so_na_normalizacao_devolve_409(client):
    _criar(client, "Carrinho de emergência")

    resposta = _criar(client, "  carrinho  de  EMERGENCIA ")

    assert resposta.status_code == 409


@pytest.mark.parametrize("nome_invalido", ["", "   ", "\t\n"])
def test_post_com_nome_vazio_devolve_422(client, nome_invalido):
    resposta = client.post("/tipos-equipamento", json={"nome": nome_invalido})

    assert resposta.status_code == 422


def test_post_sem_nome_devolve_422(client):
    resposta = client.post("/tipos-equipamento", json={"descricao": "sem nome"})

    assert resposta.status_code == 422


def test_get_lista_paginada(client):
    for indice in range(5):
        _criar(client, f"Tipo {indice}")

    resposta = client.get("/tipos-equipamento", params={"page": 1, "size": 2})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["total"] == 5
    assert corpo["pages"] == 3
    assert corpo["page"] == 1
    assert corpo["size"] == 2
    assert len(corpo["items"]) == 2


def test_get_lista_rejeita_size_acima_do_maximo(client):
    resposta = client.get("/tipos-equipamento", params={"size": 101})

    assert resposta.status_code == 422


def test_get_lista_esconde_inativos_por_padrao(client):
    criado = _criar(client, "Maca").json()
    client.post(f"/tipos-equipamento/{criado['id']}/inativar")

    padrao = client.get("/tipos-equipamento").json()
    assert padrao["total"] == 0

    com_inativos = client.get("/tipos-equipamento", params={"incluir_inativos": True}).json()
    assert com_inativos["total"] == 1


def test_get_por_id(client):
    criado = _criar(client, "Maca").json()

    resposta = client.get(f"/tipos-equipamento/{criado['id']}")

    assert resposta.status_code == 200
    assert resposta.json()["id"] == criado["id"]


def test_get_por_id_inexistente_devolve_404(client):
    resposta = client.get("/tipos-equipamento/999999")

    assert resposta.status_code == 404


def test_patch_atualiza_nome_e_descricao(client):
    criado = _criar(client, "Maca", "descrição antiga").json()

    resposta = client.patch(
        f"/tipos-equipamento/{criado['id']}",
        json={"nome": "Maca Hospitalar", "descricao": "descrição nova"},
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["nome"] == "Maca Hospitalar"
    assert corpo["descricao"] == "descrição nova"


def test_patch_sem_descricao_no_corpo_preserva_a_atual(client):
    criado = _criar(client, "Maca", "descrição original").json()

    resposta = client.patch(
        f"/tipos-equipamento/{criado['id']}", json={"nome": "Maca Hospitalar"}
    )

    assert resposta.status_code == 200
    assert resposta.json()["descricao"] == "descrição original"


def test_patch_com_descricao_nula_explicita_limpa_o_campo(client):
    criado = _criar(client, "Maca", "descrição original").json()

    resposta = client.patch(f"/tipos-equipamento/{criado['id']}", json={"descricao": None})

    assert resposta.status_code == 200
    assert resposta.json()["descricao"] is None


def test_patch_para_nome_ja_usado_devolve_409(client):
    _criar(client, "Maca")
    outro = _criar(client, "Cadeira de rodas").json()

    resposta = client.patch(f"/tipos-equipamento/{outro['id']}", json={"nome": "maca"})

    assert resposta.status_code == 409


def test_patch_com_nome_vazio_devolve_422(client):
    criado = _criar(client, "Maca").json()

    resposta = client.patch(f"/tipos-equipamento/{criado['id']}", json={"nome": "   "})

    assert resposta.status_code == 422


def test_patch_inexistente_devolve_404(client):
    resposta = client.patch("/tipos-equipamento/999999", json={"nome": "Qualquer"})

    assert resposta.status_code == 404


def test_inativar_devolve_200_e_ativo_false(client):
    criado = _criar(client, "Maca").json()

    resposta = client.post(f"/tipos-equipamento/{criado['id']}/inativar")

    assert resposta.status_code == 200
    assert resposta.json()["ativo"] is False


def test_inativar_tipo_em_uso_devolve_409(client, engine):
    criado = _criar(client, "Maca").json()
    with Session(bind=engine) as session:
        session.add(
            Equipamento(
                nome="Maca do 3o andar",
                tipo_id=criado["id"],
                identificador_interno="EQ-API-001",
            )
        )
        session.commit()

    resposta = client.post(f"/tipos-equipamento/{criado['id']}/inativar")

    assert resposta.status_code == 409


def test_inativar_inexistente_devolve_404(client):
    resposta = client.post("/tipos-equipamento/999999/inativar")

    assert resposta.status_code == 404


def test_reativar_devolve_200_e_ativo_true(client):
    criado = _criar(client, "Maca").json()
    client.post(f"/tipos-equipamento/{criado['id']}/inativar")

    resposta = client.post(f"/tipos-equipamento/{criado['id']}/reativar")

    assert resposta.status_code == 200
    assert resposta.json()["ativo"] is True


def test_reativar_inexistente_devolve_404(client):
    resposta = client.post("/tipos-equipamento/999999/reativar")

    assert resposta.status_code == 404
