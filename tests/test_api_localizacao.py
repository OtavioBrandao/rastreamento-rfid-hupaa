"""
Testes do contrato HTTP da ISS-011 (hierarquia física), via TestClient.

O alvo é o que o router promete: status code, formato do corpo e tradução
das exceções de domínio. A regra de negócio em si está em
`tests/test_service_localizacao.py`. Mesma fixture `client` do padrão das
issues anteriores (override de `get_db` + `truncate_all`).
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


def _andar(client, nome="4º Andar", **extra):
    resposta = client.post("/andares", json={"nome": nome, **extra})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _setor(client, andar_id, nome="Ala Norte", **extra):
    resposta = client.post("/setores", json={"andar_id": andar_id, "nome": nome, **extra})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _zona(client, setor_id, nome="Leito 01", **extra):
    resposta = client.post("/zonas", json={"setor_id": setor_id, "nome": nome, **extra})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


# --- POST: 201 / 409 / 422 ----------------------------------------------------------


def test_post_andar_devolve_201_com_campos_novos(client):
    resposta = client.post(
        "/andares",
        json={"nome": "  4º Andar ", "descricao": "Internação", "referencia_planta": "P-4"},
    )

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["nome"] == "4º Andar"
    assert corpo["nome_normalizado"] == "4o andar"
    assert corpo["descricao"] == "Internação"
    assert corpo["referencia_planta"] == "P-4"
    assert corpo["ativo"] is True
    assert "observacoes" not in corpo


def test_post_setor_e_zona_devolvem_201_com_o_id_do_pai(client):
    andar = _andar(client)
    setor = _setor(client, andar["id"])
    zona = _zona(client, setor["id"])

    assert setor["andar_id"] == andar["id"]
    assert zona["setor_id"] == setor["id"]


@pytest.mark.parametrize("variacao", ["4º Andar", "4o andar", "  4O  ANDAR "])
def test_post_andar_duplicado_devolve_409(client, variacao):
    _andar(client, "4º Andar")

    assert client.post("/andares", json={"nome": variacao}).status_code == 409


def test_post_setor_duplicado_no_mesmo_andar_devolve_409(client):
    andar = _andar(client)
    _setor(client, andar["id"], "Ala Norte")

    resposta = client.post("/setores", json={"andar_id": andar["id"], "nome": "ala  NORTE"})

    assert resposta.status_code == 409


def test_post_zona_duplicada_no_mesmo_setor_devolve_409(client):
    setor = _setor(client, _andar(client)["id"])
    _zona(client, setor["id"], "Leito 01")

    assert client.post("/zonas", json={"setor_id": setor["id"], "nome": "LEITO 01"}).status_code == 409


def test_mesmo_nome_em_escopos_diferentes_devolve_201(client):
    andar_3 = _andar(client, "3º Andar")
    andar_4 = _andar(client, "4º Andar")
    _setor(client, andar_3["id"], "Enfermaria")
    setor_4 = _setor(client, andar_4["id"], "Enfermaria")
    outro_setor = _setor(client, andar_4["id"], "UTI")
    _zona(client, setor_4["id"], "Leito 01")
    _zona(client, outro_setor["id"], "Leito 01")


def test_post_setor_com_andar_inexistente_devolve_422(client):
    resposta = client.post("/setores", json={"andar_id": 999999, "nome": "Ala Norte"})

    assert resposta.status_code == 422
    assert "não existe" in resposta.json()["detail"]


def test_post_setor_com_andar_inativo_devolve_422(client):
    andar = _andar(client)
    client.post(f"/andares/{andar['id']}/inativar")

    resposta = client.post("/setores", json={"andar_id": andar["id"], "nome": "Ala Norte"})

    assert resposta.status_code == 422
    assert "inativo" in resposta.json()["detail"]


def test_post_zona_com_setor_inexistente_ou_inativo_devolve_422(client):
    assert client.post("/zonas", json={"setor_id": 999999, "nome": "Leito 01"}).status_code == 422

    setor = _setor(client, _andar(client)["id"])
    client.post(f"/setores/{setor['id']}/inativar")
    assert client.post("/zonas", json={"setor_id": setor["id"], "nome": "Leito 01"}).status_code == 422


@pytest.mark.parametrize("nome", ["", "   ", "\t\n"])
def test_post_com_nome_vazio_devolve_422_nos_tres_niveis(client, nome):
    setor = _setor(client, _andar(client)["id"])

    assert client.post("/andares", json={"nome": nome}).status_code == 422
    assert client.post("/setores", json={"andar_id": 1, "nome": nome}).status_code == 422
    assert client.post("/zonas", json={"setor_id": setor["id"], "nome": nome}).status_code == 422


def test_post_com_pai_id_invalido_devolve_422(client):
    assert client.post("/setores", json={"andar_id": 0, "nome": "X"}).status_code == 422
    assert client.post("/zonas", json={"setor_id": -1, "nome": "X"}).status_code == 422
    assert client.post("/setores", json={"nome": "X"}).status_code == 422


# --- GET por id / PATCH: 200 / 404 / 409 --------------------------------------------


def test_get_por_id_nos_tres_niveis(client):
    andar = _andar(client)
    setor = _setor(client, andar["id"])
    zona = _zona(client, setor["id"])

    assert client.get(f"/andares/{andar['id']}").json()["id"] == andar["id"]
    assert client.get(f"/setores/{setor['id']}").json()["id"] == setor["id"]
    assert client.get(f"/zonas/{zona['id']}").json()["id"] == zona["id"]


@pytest.mark.parametrize("caminho", ["/andares/999999", "/setores/999999", "/zonas/999999"])
def test_get_inexistente_devolve_404(client, caminho):
    assert client.get(caminho).status_code == 404


@pytest.mark.parametrize(
    "caminho",
    [
        "/andares/999999/inativar",
        "/andares/999999/reativar",
        "/setores/999999/inativar",
        "/setores/999999/reativar",
        "/zonas/999999/inativar",
        "/zonas/999999/reativar",
    ],
)
def test_inativar_e_reativar_inexistente_devolvem_404(client, caminho):
    assert client.post(caminho).status_code == 404


def test_patch_inexistente_devolve_404(client):
    for caminho in ("/andares/999999", "/setores/999999", "/zonas/999999"):
        assert client.patch(caminho, json={"nome": "X"}).status_code == 404


def test_patch_atualiza_e_preserva_o_que_nao_veio(client):
    andar = _andar(client, descricao="orig", referencia_planta="P-4")

    resposta = client.patch(f"/andares/{andar['id']}", json={"nome": "Quarto Andar"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["nome"] == "Quarto Andar"
    assert corpo["nome_normalizado"] == "quarto andar"
    assert corpo["descricao"] == "orig"
    assert corpo["referencia_planta"] == "P-4"


def test_patch_com_null_explicito_limpa_o_campo(client):
    setor = _setor(client, _andar(client)["id"], descricao="orig", referencia_planta="P")

    corpo = client.patch(
        f"/setores/{setor['id']}", json={"descricao": None, "referencia_planta": None}
    ).json()

    assert corpo["descricao"] is None and corpo["referencia_planta"] is None


def test_patch_para_nome_ja_usado_no_escopo_devolve_409(client):
    setor = _setor(client, _andar(client)["id"])
    _zona(client, setor["id"], "Leito 01")
    outra = _zona(client, setor["id"], "Leito 02")

    resposta = client.patch(f"/zonas/{outra['id']}", json={"nome": "LEITO 01"})

    assert resposta.status_code == 409


def test_patch_com_nome_vazio_devolve_422(client):
    andar = _andar(client)

    assert client.patch(f"/andares/{andar['id']}", json={"nome": "  "}).status_code == 422


def test_patch_de_setor_ignora_andar_id_no_corpo(client):
    """
    A hierarquia é imutável (decisão confirmada: não se reparenta). `andar_id`
    no corpo do PATCH não dá erro e não tem efeito — o schema de update nem
    declara o campo, e o Pydantic descarta o que não conhece. Os campos
    legítimos do MESMO corpo continuam sendo aplicados.
    """
    andar_a = _andar(client, "3º Andar")
    andar_b = _andar(client, "4º Andar")
    setor = _setor(client, andar_a["id"], "Enfermaria")

    resposta = client.patch(
        f"/setores/{setor['id']}", json={"andar_id": andar_b["id"], "nome": "UTI"}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["andar_id"] == andar_a["id"]  # não moveu
    assert corpo["nome"] == "UTI"  # o resto do corpo foi aplicado
    assert client.get(f"/setores/{setor['id']}").json()["andar_id"] == andar_a["id"]


def test_patch_de_setor_ignora_andar_id_ate_quando_invalido(client):
    """Nem valida o campo: um id inexistente ou de tipo errado também é só ignorado."""
    andar = _andar(client)
    setor = _setor(client, andar["id"])

    for valor in (999999, 0, "abc", None):
        resposta = client.patch(f"/setores/{setor['id']}", json={"andar_id": valor})
        assert resposta.status_code == 200, valor
        assert resposta.json()["andar_id"] == andar["id"]


def test_patch_de_zona_ignora_setor_id_no_corpo(client):
    andar = _andar(client)
    setor_a = _setor(client, andar["id"], "Ala Norte")
    setor_b = _setor(client, andar["id"], "Ala Sul")
    zona = _zona(client, setor_a["id"], "Leito 01")

    resposta = client.patch(
        f"/zonas/{zona['id']}", json={"setor_id": setor_b["id"], "nome": "Leito 99"}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["setor_id"] == setor_a["id"]  # não moveu
    assert corpo["nome"] == "Leito 99"  # o resto do corpo foi aplicado
    assert client.get(f"/zonas/{zona['id']}").json()["setor_id"] == setor_a["id"]


def test_patch_de_zona_ignora_setor_id_ate_quando_invalido(client):
    setor = _setor(client, _andar(client)["id"])
    zona = _zona(client, setor["id"])

    for valor in (999999, 0, "abc", None):
        resposta = client.patch(f"/zonas/{zona['id']}", json={"setor_id": valor})
        assert resposta.status_code == 200, valor
        assert resposta.json()["setor_id"] == setor["id"]


# --- observacoes (zona morta): só a zona ------------------------------------------------------


def test_post_zona_aceita_observacoes_e_devolve_no_corpo(client):
    setor = _setor(client, _andar(client)["id"])

    corpo = _zona(client, setor["id"], "Leito 02", observacoes="zona morta perto da janela")

    assert corpo["observacoes"] == "zona morta perto da janela"
    assert client.get(f"/zonas/{corpo['id']}").json()["observacoes"] == "zona morta perto da janela"


def test_post_zona_sem_observacoes_devolve_null(client):
    setor = _setor(client, _andar(client)["id"])

    assert _zona(client, setor["id"])["observacoes"] is None


def test_patch_de_zona_atualiza_preserva_e_limpa_observacoes(client):
    setor = _setor(client, _andar(client)["id"])
    zona = _zona(client, setor["id"], observacoes="zona morta")

    # sem o campo no corpo: preserva
    corpo = client.patch(f"/zonas/{zona['id']}", json={"nome": "Leito 03"}).json()
    assert corpo["observacoes"] == "zona morta"

    # com valor: atualiza
    corpo = client.patch(f"/zonas/{zona['id']}", json={"observacoes": "sem sinal no fundo"}).json()
    assert corpo["observacoes"] == "sem sinal no fundo"

    # com null explícito: limpa
    corpo = client.patch(f"/zonas/{zona['id']}", json={"observacoes": None}).json()
    assert corpo["observacoes"] is None


def test_lista_de_zonas_e_arvore_trazem_observacoes(client):
    andar = _andar(client)
    setor = _setor(client, andar["id"])
    _zona(client, setor["id"], "Leito 02", observacoes="zona morta")

    lista = client.get("/zonas").json()["items"]
    (raiz,) = client.get("/localizacoes/arvore").json()

    assert lista[0]["observacoes"] == "zona morta"
    assert raiz["setores"][0]["zonas"][0]["observacoes"] == "zona morta"


def test_andar_e_setor_nao_tem_observacoes(client):
    andar = _andar(client)
    setor = _setor(client, andar["id"])

    assert "observacoes" not in andar
    assert "observacoes" not in setor


# --- inativar / reativar ----------------------------------------------------------------


def test_inativar_setor_com_zona_ativa_devolve_409_e_nada_muda(client):
    andar = _andar(client)
    setor = _setor(client, andar["id"])
    zona = _zona(client, setor["id"])

    resposta = client.post(f"/setores/{setor['id']}/inativar")

    assert resposta.status_code == 409
    assert client.get(f"/setores/{setor['id']}").json()["ativo"] is True
    assert client.get(f"/zonas/{zona['id']}").json()["ativo"] is True


def test_inativar_andar_com_setor_ativo_devolve_409(client):
    andar = _andar(client)
    _setor(client, andar["id"])

    assert client.post(f"/andares/{andar['id']}/inativar").status_code == 409


def test_inativar_de_baixo_para_cima_e_idempotente(client):
    andar = _andar(client)
    setor = _setor(client, andar["id"])
    zona = _zona(client, setor["id"])

    for caminho in (
        f"/zonas/{zona['id']}/inativar",
        f"/zonas/{zona['id']}/inativar",
        f"/setores/{setor['id']}/inativar",
        f"/andares/{andar['id']}/inativar",
    ):
        resposta = client.post(caminho)
        assert resposta.status_code == 200, (caminho, resposta.text)
        assert resposta.json()["ativo"] is False

    # a linha continua existindo
    assert client.get(f"/zonas/{zona['id']}").status_code == 200


def test_reativar_devolve_200_e_ativo_true(client):
    zona = _zona(client, _setor(client, _andar(client)["id"])["id"])
    client.post(f"/zonas/{zona['id']}/inativar")

    resposta = client.post(f"/zonas/{zona['id']}/reativar")

    assert resposta.status_code == 200
    assert resposta.json()["ativo"] is True


# --- listagens ----------------------------------------------------------------------------


def test_get_lista_paginada_e_esconde_inativos(client):
    for indice in range(5):
        _andar(client, f"Andar {indice}")
    client.post("/andares/1/inativar")

    padrao = client.get("/andares", params={"size": 2}).json()
    assert (padrao["total"], padrao["pages"], len(padrao["items"])) == (4, 2, 2)

    completa = client.get("/andares", params={"incluir_inativos": True}).json()
    assert completa["total"] == 5


def test_get_lista_rejeita_size_acima_do_maximo(client):
    assert client.get("/andares", params={"size": 101}).status_code == 422
    assert client.get("/setores", params={"page": 0}).status_code == 422


def test_get_setores_filtra_por_andar_id_e_zonas_por_setor_id(client):
    andar_a = _andar(client, "3º Andar")
    andar_b = _andar(client, "4º Andar")
    setor_a = _setor(client, andar_a["id"], "Enfermaria")
    _setor(client, andar_b["id"], "UTI")
    _zona(client, setor_a["id"], "Leito 01")
    setor_b = _setor(client, andar_b["id"], "Ala Sul")
    _zona(client, setor_b["id"], "Leito 01")

    setores = client.get("/setores", params={"andar_id": andar_b["id"]}).json()
    zonas = client.get("/zonas", params={"setor_id": setor_a["id"]}).json()

    assert setores["total"] == 2
    assert all(s["andar_id"] == andar_b["id"] for s in setores["items"])
    assert zonas["total"] == 1 and zonas["items"][0]["setor_id"] == setor_a["id"]


# --- árvore ----------------------------------------------------------------------------------


def _montar(client):
    andar = _andar(client)
    norte = _setor(client, andar["id"], "Ala Norte")
    sul = _setor(client, andar["id"], "Ala Sul")
    z1 = _zona(client, norte["id"], "Corredor")
    z2 = _zona(client, norte["id"], "Leito 01")
    z3 = _zona(client, sul["id"], "Corredor")
    return andar, norte, sul, z1, z2, z3


def test_arvore_completa_aninha_andares_setores_e_zonas(client):
    andar, norte, sul, z1, z2, z3 = _montar(client)

    resposta = client.get("/localizacoes/arvore")

    assert resposta.status_code == 200
    (raiz,) = resposta.json()
    assert raiz["id"] == andar["id"]
    assert [s["id"] for s in raiz["setores"]] == [norte["id"], sul["id"]]
    assert [z["id"] for z in raiz["setores"][0]["zonas"]] == [z1["id"], z2["id"]]
    assert [z["id"] for z in raiz["setores"][1]["zonas"]] == [z3["id"]]


def test_arvore_do_andar(client):
    andar, norte, *_ = _montar(client)
    _andar(client, "5º Andar")

    resposta = client.get(f"/andares/{andar['id']}/arvore")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["id"] == andar["id"]
    assert corpo["setores"][0]["id"] == norte["id"]


def test_arvore_do_andar_inexistente_devolve_404(client):
    assert client.get("/andares/999999/arvore").status_code == 404


def test_rotas_de_arvore_nao_sao_capturadas_pelas_rotas_de_path_param(client):
    """'arvore' nunca pode ser interpretado como andar_id (que seria 422)."""
    andar, *_ = _montar(client)

    assert client.get("/localizacoes/arvore").status_code == 200
    assert client.get(f"/andares/{andar['id']}/arvore").status_code == 200


def test_arvore_esconde_inativos_por_padrao_e_mostra_com_incluir_inativos(client):
    andar, norte, sul, z1, z2, z3 = _montar(client)
    for zona in (z1, z2, z3):
        client.post(f"/zonas/{zona['id']}/inativar")
    client.post(f"/setores/{norte['id']}/inativar")
    client.post(f"/setores/{sul['id']}/inativar")
    client.post(f"/andares/{andar['id']}/inativar")

    assert client.get("/localizacoes/arvore").json() == []

    (raiz,) = client.get("/localizacoes/arvore", params={"incluir_inativos": True}).json()
    assert raiz["ativo"] is False
    assert all(s["ativo"] is False for s in raiz["setores"])
    assert all(z["ativo"] is False for s in raiz["setores"] for z in s["zonas"])
    assert sum(len(s["zonas"]) for s in raiz["setores"]) == 3


# --- reativar de cima para baixo: 409 quando o pai está inativo -------------------------------


def _inativar_tudo(client, andar, setor, zona):
    for caminho in (
        f"/zonas/{zona['id']}/inativar",
        f"/setores/{setor['id']}/inativar",
        f"/andares/{andar['id']}/inativar",
    ):
        assert client.post(caminho).status_code == 200, caminho


def test_reativar_zona_com_setor_inativo_devolve_409_e_nada_muda(client):
    andar = _andar(client)
    setor = _setor(client, andar["id"])
    zona = _zona(client, setor["id"])
    _inativar_tudo(client, andar, setor, zona)

    resposta = client.post(f"/zonas/{zona['id']}/reativar")

    assert resposta.status_code == 409
    assert "setor" in resposta.json()["detail"]
    assert client.get(f"/zonas/{zona['id']}").json()["ativo"] is False


def test_reativar_setor_com_andar_inativo_devolve_409_e_nada_muda(client):
    andar = _andar(client)
    setor = _setor(client, andar["id"])
    zona = _zona(client, setor["id"])
    _inativar_tudo(client, andar, setor, zona)

    resposta = client.post(f"/setores/{setor['id']}/reativar")

    assert resposta.status_code == 409
    assert "andar" in resposta.json()["detail"]
    assert client.get(f"/setores/{setor['id']}").json()["ativo"] is False


def test_reativar_de_cima_para_baixo_devolve_200_em_cada_passo(client):
    andar = _andar(client)
    setor = _setor(client, andar["id"])
    zona = _zona(client, setor["id"])
    _inativar_tudo(client, andar, setor, zona)

    for caminho in (
        f"/andares/{andar['id']}/reativar",
        f"/setores/{setor['id']}/reativar",
        f"/zonas/{zona['id']}/reativar",
    ):
        resposta = client.post(caminho)
        assert resposta.status_code == 200, (caminho, resposta.text)
        assert resposta.json()["ativo"] is True

    # e a zona reativada volta a aparecer na árvore padrão
    (raiz,) = client.get("/localizacoes/arvore").json()
    assert raiz["setores"][0]["zonas"][0]["id"] == zona["id"]


def test_reativar_com_pai_ativo_funciona_no_caso_normal(client):
    """Só o filho está inativo; o pai continua ativo."""
    setor = _setor(client, _andar(client)["id"])
    zona = _zona(client, setor["id"])
    client.post(f"/zonas/{zona['id']}/inativar")

    assert client.post(f"/zonas/{zona['id']}/reativar").status_code == 200
