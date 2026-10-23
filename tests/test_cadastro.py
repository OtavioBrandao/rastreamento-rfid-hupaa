"""Cadastro pelo dashboard: manual, por EPC detectado, sem tag e permissões."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from api.database import get_db
from api.main import app
from api.router_cadastro import _contexto_descoberta
from db.models import (
    Andar,
    Antena,
    AssociacaoTagEquipamento,
    Auditoria,
    Equipamento,
    Leitor,
    LeituraBruta,
    Setor,
    Zona,
)

AGORA = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
EPC_1 = "E2000017221101441890A001"
EPC_2 = "E2000017221101441890A002"
EPC_3 = "E2000017221101441890A003"


@pytest.fixture
def client(engine, truncate_all):
    def get_db_de_teste():
        session = Session(bind=engine)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = get_db_de_teste
    app.dependency_overrides[_contexto_descoberta] = lambda: AGORA
    try:
        with TestClient(app) as cliente:
            yield cliente
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(_contexto_descoberta, None)


@pytest.fixture
def tipo(client) -> dict:
    resposta = client.post("/tipos-equipamento", json={"nome": "Maca"})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


@pytest.fixture
def antenas(engine) -> dict[str, int]:
    """Um leitor físico e um virtual, uma antena cada."""
    with Session(engine) as session:
        andar = Andar(nome="Andar teste", nome_normalizado="andar teste")
        session.add(andar)
        session.flush()
        setor = Setor(andar_id=andar.id, nome="Setor", nome_normalizado="setor")
        session.add(setor)
        session.flush()
        zona = Zona(setor_id=setor.id, nome="Zona A", nome_normalizado="zona a")
        session.add(zona)
        session.flush()
        ids = {}
        for reader_id, serial in (("reader-01", "LAB-1"), ("sim-hupaa-01", "SIM-L1-sim-hupaa-01")):
            leitor = Leitor(reader_id=reader_id, fabricante="Identix", modelo="EZ700",
                            identificador_serial=serial, ultimo_contato_em=AGORA)
            session.add(leitor)
            session.flush()
            antena = Antena(leitor_id=leitor.id, porta_numero=1, zona_associada_id=zona.id,
                            funcao="entrada")
            session.add(antena)
            session.flush()
            ids[reader_id] = antena.id
        session.commit()
        return ids


def _ler(engine, antena_id: int, epc: str, em: datetime, n: int = 1) -> None:
    with Session(engine) as session:
        for indice in range(n):
            session.add(LeituraBruta(
                event_id=f"sha256:{epc}{antena_id}{em.timestamp()}{indice}".ljust(71, "0")[:71],
                antena_id=antena_id, epc=epc, lido_em=em + timedelta(milliseconds=indice)))
        session.commit()


def _cadastrar(client, tipo_id: int, **campos) -> object:
    return client.post("/api/cadastro/equipamentos", json={"tipo_id": tipo_id, **campos})


def test_cadastro_manual_sem_patrimonio_gera_identificador(client, tipo):
    resposta = _cadastrar(client, tipo["id"], nome="Maca hospitalar", epc=EPC_1.lower(),
                          confirmar_associacao=True)
    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["epc"] == EPC_1
    assert corpo["situacao_tag"] == "com_tag"
    assert corpo["identificador_interno"].startswith("EQ-")


def test_nomes_repetidos_sao_equipamentos_diferentes(client, tipo):
    ids = set()
    for epc in (EPC_1, EPC_2, EPC_3):
        resposta = _cadastrar(client, tipo["id"], nome="Maca hospitalar", epc=epc,
                              confirmar_associacao=True)
        assert resposta.status_code == 201, resposta.text
        ids.add(resposta.json()["id"])
    assert len(ids) == 3
    lista = client.get("/api/cadastro/equipamentos", params={"busca": "maca"}).json()
    assert lista["total"] == 3
    assert {item["epc"] for item in lista["items"]} == {EPC_1, EPC_2, EPC_3}


def test_epc_duplicado_nao_deixa_equipamento_orfao(client, tipo, engine):
    assert _cadastrar(client, tipo["id"], nome="Maca 1", epc=EPC_1,
                      confirmar_associacao=True).status_code == 201
    resposta = _cadastrar(client, tipo["id"], nome="Maca 2", epc=EPC_1, confirmar_associacao=True)
    assert resposta.status_code == 409
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Equipamento)) == 1


def test_associacao_exige_confirmacao_e_epc_valido(client, tipo):
    assert _cadastrar(client, tipo["id"], nome="Maca", epc=EPC_1).status_code == 422
    assert _cadastrar(client, tipo["id"], nome="Maca", epc="XYZ",
                      confirmar_associacao=True).status_code == 422
    assert _cadastrar(client, tipo["id"], nome="   ").status_code == 422


def test_patrimonio_duplicado_conflita(client, tipo):
    assert _cadastrar(client, tipo["id"], nome="Maca", identificador_interno="PAT-1"
                      ).status_code == 201
    assert _cadastrar(client, tipo["id"], nome="Maca", identificador_interno="pat-1"
                      ).status_code == 409


def test_equipamento_sem_tag_e_associacao_posterior(client, tipo, engine, antenas):
    criado = _cadastrar(client, tipo["id"], nome="Cadeira de rodas").json()
    assert criado["situacao_tag"] == "sem_tag" and criado["epc"] is None
    sem_tag = client.get("/api/cadastro/equipamentos", params={"situacao": "sem_tag"}).json()
    assert [item["id"] for item in sem_tag["items"]] == [criado["id"]]

    # Sem EPC, o equipamento não tem como ser resolvido por leitura alguma.
    _ler(engine, antenas["reader-01"], EPC_2, AGORA - timedelta(seconds=5))
    deteccao = client.get("/api/cadastro/epcs-detectados").json()
    assert deteccao["items"][0]["situacao"] == "desconhecido"

    resposta = client.post(f"/equipamentos/{criado['id']}/tag", json={"epc": EPC_2})
    assert resposta.status_code == 201, resposta.text
    com_tag = client.get("/api/cadastro/equipamentos", params={"situacao": "com_tag"}).json()
    assert com_tag["items"][0]["epc"] == EPC_2
    deteccao = client.get("/api/cadastro/epcs-detectados").json()
    assert deteccao["items"][0]["situacao"] == "cadastrado"
    assert deteccao["items"][0]["equipamento"]["id"] == criado["id"]


def test_descoberta_consolida_filtra_e_marca_recencia(client, tipo, engine, antenas):
    _ler(engine, antenas["reader-01"], EPC_1, AGORA - timedelta(seconds=30), n=3)
    _ler(engine, antenas["sim-hupaa-01"], EPC_1, AGORA - timedelta(seconds=10), n=2)
    _ler(engine, antenas["reader-01"], EPC_2, AGORA - timedelta(minutes=10))
    _ler(engine, antenas["reader-01"], EPC_3, AGORA - timedelta(hours=2))  # fora da janela
    assert _cadastrar(client, tipo["id"], nome="Maca", epc=EPC_2,
                      confirmar_associacao=True).status_code == 201

    corpo = client.get("/api/cadastro/epcs-detectados").json()
    assert corpo["total"] == 2 and corpo["desconhecidos"] == 1
    primeiro = corpo["items"][0]
    assert primeiro["epc"] == EPC_1 and primeiro["leituras"] == 5
    assert primeiro["recente"] is True
    assert primeiro["ultima_antena"]["leitor"] == "sim-hupaa-01"
    assert primeiro["ultima_antena"]["origem"] == "simulado"
    assert {antena["leitor"] for antena in primeiro["antenas"]} == {"reader-01", "sim-hupaa-01"}
    assert corpo["items"][1]["recente"] is False

    desconhecidos = client.get("/api/cadastro/epcs-detectados",
                               params={"situacao": "desconhecidos"}).json()
    assert [item["epc"] for item in desconhecidos["items"]] == [EPC_1]
    por_leitor = client.get("/api/cadastro/epcs-detectados",
                            params={"leitor": "sim-hupaa-01"}).json()
    assert [item["epc"] for item in por_leitor["items"]] == [EPC_1]
    assert por_leitor["items"][0]["leituras"] == 2
    por_antena = client.get("/api/cadastro/epcs-detectados",
                            params={"antena_id": antenas["reader-01"], "janela_segundos": 60}
                            ).json()
    assert [item["epc"] for item in por_antena["items"]] == [EPC_1]
    assert {leitor["reader_id"] for leitor in corpo["leitores"]} == {"reader-01", "sim-hupaa-01"}


def test_cadastro_por_epc_detectado_cria_vinculo_e_auditoria(client, tipo, engine, antenas):
    _ler(engine, antenas["sim-hupaa-01"], EPC_3, AGORA - timedelta(seconds=3))
    epc = client.get("/api/cadastro/epcs-detectados",
                     params={"situacao": "desconhecidos"}).json()["items"][0]["epc"]
    assert client.get(f"/api/cadastro/epcs/{epc}").json()["disponivel"] is True
    resposta = _cadastrar(client, tipo["id"], nome="Maca hospitalar", epc=epc,
                          origem_epc="leitura", confirmar_associacao=True)
    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["origem_epc"] == "leitura"
    assert client.get(f"/api/cadastro/epcs/{epc}").json()["disponivel"] is False
    with Session(engine) as session:
        acoes = set(session.scalars(select(Auditoria.acao)))
        assert {"criar", "vincular_epc"} <= acoes
        vinculo = session.scalar(select(AssociacaoTagEquipamento))
        # O cadastro não move o equipamento: localização só por passagem confirmada.
        equipamento = session.get(Equipamento, vinculo.equipamento_id)
        assert equipamento.ultima_zona_id is None


@pytest.mark.autenticacao_real
def test_operacional_consulta_mas_nao_cadastra(api_auth, engine, truncate_all):
    from suporte_auth import inserir_usuario, logar

    inserir_usuario(engine, "operador@hupaa.example", perfil="operacional")
    cliente = api_auth()
    logar(cliente, "operador@hupaa.example")
    assert cliente.get("/api/cadastro/epcs-detectados").status_code == 200
    with engine.begin() as conexao:
        tipo_id = conexao.execute(text(
            "INSERT INTO tipos_equipamento (nome, nome_normalizado) VALUES ('Maca', 'maca') "
            "RETURNING id")).scalar_one()
    resposta = cliente.post("/api/cadastro/equipamentos", json={"nome": "Maca", "tipo_id": tipo_id})
    assert resposta.status_code == 403
