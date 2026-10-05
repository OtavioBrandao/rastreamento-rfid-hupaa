"""Presença por leitura bruta: contagem por tag/antena e última leitura do ativo."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.database import get_db
from api.main import app
from api.service_busca_ativos import buscar
from api.service_leituras import resumo
from db.models import Antena, LeituraBruta
from tools.lab_launcher.seed import semear, semear_equipamentos

AGORA = datetime(2026, 10, 5, 20, 25, tzinfo=timezone.utc)
CAIXA = "3034000000000C40000000DA"
ISOPOR = "3034000000000C4000000105"
PARADO = "3034000000000C40000000DF"
AVULSA = "3034000000000C400000012F"


def _ler(db, antena, epc, quando):
    _ler.seq += 1
    db.add(LeituraBruta(event_id=f"sha256:{_ler.seq:064x}", antena_id=antena.id,
                        epc=epc, lido_em=quando))


_ler.seq = 0


def _cenario(db):
    semear(db)
    semear_equipamentos(db, [(CAIXA, "CAIXA EZ700"), (ISOPOR, "CAIXA DE ISOPOR"),
                             (PARADO, "RECIPIENTE DE PLASTICO")])
    antenas = {a.porta_numero: a for a in db.scalars(select(Antena))}
    for segundo in range(10):
        _ler(db, antenas[1], CAIXA, AGORA - timedelta(seconds=segundo))
        _ler(db, antenas[2], ISOPOR, AGORA - timedelta(seconds=segundo))
    for segundo in range(3):
        _ler(db, antenas[1], AVULSA, AGORA - timedelta(seconds=segundo))
    _ler(db, antenas[2], AVULSA, AGORA - timedelta(seconds=5))
    _ler(db, antenas[2], PARADO, AGORA - timedelta(minutes=20))
    db.flush()


def test_resumo_conta_por_antena_e_separa_cadastradas(db):
    _cenario(db)
    dados = resumo(db, now=AGORA, janela=timedelta(seconds=60))
    por_epc = {item["epc"]: item for item in dados["items"]}

    assert [item["epc"] for item in dados["items"]][:3] == [CAIXA, ISOPOR, PARADO]
    assert por_epc[CAIXA]["equipamento"]["nome"] == "CAIXA EZ700"
    assert por_epc[CAIXA]["leituras"] == 10
    assert por_epc[CAIXA]["ultima_leitura"]["porta"] == 1
    assert por_epc[CAIXA]["ultima_leitura"]["zona"] == "Zona A"
    assert por_epc[ISOPOR]["ultima_leitura"]["zona"] == "Zona B"
    # Cadastrada fora da janela aparece com zero e a última leitura antiga.
    assert por_epc[PARADO]["leituras"] == 0
    assert por_epc[PARADO]["ultima_leitura"]["em"] == AGORA - timedelta(minutes=20)
    assert por_epc[AVULSA]["cadastrada"] is False
    assert sorted(x["leituras"] for x in por_epc[AVULSA]["leituras_por_antena"]) == [1, 3]
    assert (dados["total_leituras"], dados["cadastradas_detectadas"],
            dados["cadastradas_sem_leitura"], dados["nao_cadastradas"]) == (24, 2, 1, 1)
    assert [a["porta"] for a in dados["antenas"]] == [1, 2]

    somente = resumo(db, now=AGORA, janela=timedelta(seconds=60), somente_cadastradas=True)
    assert AVULSA not in {item["epc"] for item in somente["items"]}


def test_busca_de_ativos_expoe_ultima_leitura_sem_alterar_zona(db):
    _cenario(db)
    pagina = buscar(db, now=AGORA, threshold=timedelta(minutes=30), page_size=100)
    por_nome = {item.nome: item for item in pagina.items}
    caixa = por_nome["CAIXA EZ700"]
    assert caixa.status == "nunca_detectado"
    assert caixa.ultima_zona is None
    assert caixa.ultima_leitura.porta == 1
    assert caixa.ultima_leitura.zona == "Zona A"
    assert caixa.ultima_leitura.em == AGORA
    assert por_nome["RECIPIENTE DE PLASTICO"].ultima_leitura.em == AGORA - timedelta(minutes=20)


def test_endpoint_valida_janela(db):
    _cenario(db)
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            assert client.get("/api/leituras/resumo?janela_segundos=1").status_code == 422
            assert client.get("/api/leituras/resumo?janela_segundos=86401").status_code == 422
            resposta = client.get("/api/leituras/resumo?janela_segundos=30"
                                  "&somente_cadastradas=true")
            assert resposta.status_code == 200
            dados = resposta.json()
            assert dados["janela_segundos"] == 30
            assert {item["epc"] for item in dados["items"]} == {CAIXA, ISOPOR, PARADO}
    finally:
        app.dependency_overrides.clear()
