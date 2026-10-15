"""
Correção manual de localização e de cadastro (ISS-025), contra Postgres real,
com login e cookie de verdade. As fixtures `admin_logado`, `api_auth`,
`relogio` vêm do conftest; daqui só se importam helpers.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session
from suporte_auth import INICIO, consultar, executar, inserir_usuario, logar

from api import auditoria, service_correcoes, service_equipamento
from db.models import TipoEquipamento
from rfid_location import repository as location_repository

pytestmark = pytest.mark.autenticacao_real

JUSTIFICATIVA = "Equipamento visto na sala D pela enfermagem"


@dataclass
class Cenario:
    cliente: TestClient
    admin_id: int
    tipos: dict
    zonas: dict
    equipamento_id: int
    outro_id: int


def _ok(resposta, esperado=(200, 201)):
    assert resposta.status_code in (esperado if isinstance(esperado, tuple) else (esperado,)), (
        resposta.text)
    return resposta.json()


@pytest.fixture
def cenario(admin_logado) -> Cenario:
    cliente, admin_id = admin_logado
    tipos = {nome: _ok(cliente.post("/tipos-equipamento", json={"nome": nome}))["id"]
             for nome in ("Maca", "Bomba", "Antigo")}
    _ok(cliente.post(f"/tipos-equipamento/{tipos['Antigo']}/inativar"))
    andar = _ok(cliente.post("/andares", json={"nome": "2º andar"}))["id"]
    setor = _ok(cliente.post("/setores", json={"andar_id": andar, "nome": "Bloco B"}))["id"]
    zonas = {nome: _ok(cliente.post("/zonas", json={"setor_id": setor, "nome": f"Zona {nome}"}))["id"]
             for nome in ("C", "D", "X")}
    _ok(cliente.post(f"/zonas/{zonas['X']}/inativar"))
    equipamento = _ok(cliente.post("/equipamentos", json={
        "nome": "Maca 01", "tipo_id": tipos["Maca"], "identificador_interno": "PAT-001",
        "descricao": "Maca de transporte"}))["id"]
    outro = _ok(cliente.post("/equipamentos", json={
        "nome": "Maca 02", "tipo_id": tipos["Maca"], "identificador_interno": "PAT-002"}))["id"]
    return Cenario(cliente, admin_id, tipos, zonas, equipamento, outro)


def _versao(engine, equipamento_id) -> int:
    return consultar(engine, "SELECT versao FROM equipamentos WHERE id=:id", id=equipamento_id)[0][0]


def _estado(engine, equipamento_id) -> dict:
    """Tudo o que uma correção poderia gravar, para comparar antes/depois."""
    return {
        "historico": consultar(engine, "SELECT * FROM historico_movimentacoes ORDER BY id"),
        "equipamento": consultar(engine, "SELECT nome, tipo_id, identificador_interno, descricao, "
                                 "status, ultima_zona_id, ultima_deteccao_em, ultima_passagem_id, "
                                 "ultima_movimentacao_id, versao FROM equipamentos WHERE id=:id",
                                 id=equipamento_id),
        "auditoria": consultar(engine, "SELECT id FROM auditorias WHERE acao <> 'acesso_negado' "
                               "ORDER BY id"),
    }


def _localizacao(cenario, zona, versao, **extra):
    return cenario.cliente.post(
        f"/equipamentos/{cenario.equipamento_id}/correcoes/localizacao",
        json={"zona_id": zona, "justificativa": JUSTIFICATIVA, "versao_esperada": versao, **extra})


def _cadastro(cenario, versao, **campos):
    return cenario.cliente.post(
        f"/equipamentos/{cenario.equipamento_id}/correcoes/cadastro",
        json={"justificativa": "Patrimônio digitado errado no cadastro", "versao_esperada": versao,
              **campos})


def _auditorias(engine, acao) -> list[dict]:
    colunas = ("usuario_id", "origem", "entidade", "entidade_id", "motivo", "dados_antes",
               "dados_depois")
    return [dict(zip(colunas, linha)) for linha in consultar(
        engine, f"SELECT {', '.join(colunas)} FROM auditorias WHERE acao = :acao ORDER BY id",
        acao=acao)]


# --- localização ------------------------------------------------------------------


def test_correcao_de_localizacao_grava_ledger_projecao_auditoria_e_resposta(engine, cenario):
    versao = _versao(engine, cenario.equipamento_id)

    resposta = _localizacao(cenario, cenario.zonas["D"], versao, referencia="  OS-123  ")

    corpo = _ok(resposta, 200)
    (evento,) = consultar(engine, "SELECT id, origem_registro, zona_origem_id, zona_destino_id, "
                          "justificativa, referencia, movimentada_em, registro_anterior_id, "
                          "passagem_id FROM historico_movimentacoes")
    assert evento[1:] == ("correcao_manual", None, cenario.zonas["D"], JUSTIFICATIVA, "OS-123",
                          INICIO, None, None)
    assert consultar(engine, "SELECT ultima_zona_id, ultima_deteccao_em, ultima_passagem_id, "
                     "ultima_movimentacao_id, versao FROM equipamentos WHERE id=:id",
                     id=cenario.equipamento_id) == [
        (cenario.zonas["D"], INICIO, None, evento[0], versao + 1)]
    assert corpo == {"equipamento_id": cenario.equipamento_id, "zona_anterior_id": None,
                     "zona_id": cenario.zonas["D"], "movimentacao_id": evento[0],
                     "movimentada_em": "2026-09-28T12:00:00Z", "versao": versao + 1}
    (linha,) = _auditorias(engine, "correcao_manual")
    assert linha == {
        "usuario_id": cenario.admin_id, "origem": "usuario", "entidade": "equipamentos",
        "entidade_id": cenario.equipamento_id, "motivo": JUSTIFICATIVA,
        "dados_antes": {"ultima_zona_id": None, "zona": None, "ultima_deteccao_em": None},
        "dados_depois": {"ultima_zona_id": cenario.zonas["D"], "zona": "Zona D",
                         "ultima_deteccao_em": INICIO.isoformat(),
                         "movimentacao_id": evento[0], "referencia": "OS-123"},
    }
    historico = cenario.cliente.get(f"/equipamentos/{cenario.equipamento_id}/movimentacoes").json()
    assert [(i["origem_registro"], i["referencia"]) for i in historico["items"]] == [
        ("correcao_manual", "OS-123")]


def test_segunda_correcao_preserva_a_primeira_e_encadeia(engine, cenario, relogio):
    _ok(_localizacao(cenario, cenario.zonas["C"], _versao(engine, cenario.equipamento_id)), 200)
    primeira = consultar(engine, "SELECT * FROM historico_movimentacoes")
    relogio.avancar(minutes=5)

    corpo = _ok(_localizacao(cenario, cenario.zonas["D"], _versao(engine, cenario.equipamento_id)),
                200)

    linhas = consultar(engine, "SELECT id, zona_origem_id, zona_destino_id, registro_anterior_id "
                       "FROM historico_movimentacoes ORDER BY id")
    assert consultar(engine, "SELECT * FROM historico_movimentacoes ORDER BY id")[0] == primeira[0]
    assert linhas[1] == (corpo["movimentacao_id"], cenario.zonas["C"], cenario.zonas["D"],
                         linhas[0][0])
    assert corpo["zona_anterior_id"] == cenario.zonas["C"]
    antes = _auditorias(engine, "correcao_manual")[-1]["dados_antes"]
    assert (antes["ultima_zona_id"], antes["zona"]) == (cenario.zonas["C"], "Zona C")


def _preparar_mesma_zona(engine, cenario, relogio):
    _ok(_localizacao(cenario, cenario.zonas["C"], _versao(engine, cenario.equipamento_id)), 200)
    relogio.avancar(minutes=1)
    return cenario.zonas["C"], 422, "sem_mudanca"


def _preparar_zona_inativa(engine, cenario, relogio):
    return cenario.zonas["X"], 422, "zona_invalida"


def _preparar_zona_inexistente(engine, cenario, relogio):
    return 999_999, 422, "zona_invalida"


def _preparar_inativo(engine, cenario, relogio):
    _ok(cenario.cliente.post(f"/equipamentos/{cenario.equipamento_id}/inativar"), 200)
    return cenario.zonas["D"], 409, "equipamento_inativo"


def _preparar_deteccao_futura(engine, cenario, relogio):
    executar(engine, "UPDATE equipamentos SET ultima_deteccao_em = :t WHERE id = :id",
             t=INICIO + timedelta(hours=1), id=cenario.equipamento_id)
    return cenario.zonas["D"], 409, "anterior_a_ultima_localizacao"


@pytest.mark.parametrize("preparar", [
    _preparar_mesma_zona, _preparar_zona_inativa, _preparar_zona_inexistente,
    _preparar_inativo, _preparar_deteccao_futura,
], ids=["mesma-zona", "zona-inativa", "zona-inexistente", "equipamento-inativo",
        "deteccao-no-futuro"])
def test_recusas_de_localizacao_nao_gravam_nada(engine, cenario, relogio, preparar):
    zona, status, codigo = preparar(engine, cenario, relogio)
    antes = _estado(engine, cenario.equipamento_id)

    resposta = _localizacao(cenario, zona, _versao(engine, cenario.equipamento_id))

    assert resposta.status_code == status, resposta.text
    assert resposta.json()["detail"]["codigo"] == codigo
    assert resposta.json()["detail"]["mensagem"]
    assert _estado(engine, cenario.equipamento_id) == antes


def test_localizacao_mesmo_horario_da_ultima_deteccao_conflita(engine, cenario):
    executar(engine, "UPDATE equipamentos SET ultima_deteccao_em = :t WHERE id = :id",
             t=INICIO, id=cenario.equipamento_id)

    resposta = _localizacao(cenario, cenario.zonas["D"], _versao(engine, cenario.equipamento_id))

    assert (resposta.status_code, resposta.json()["detail"]["codigo"]) == (
        409, "conflito_de_horario")


def test_equipamento_inexistente_404(cenario):
    resposta = cenario.cliente.post("/equipamentos/999999/correcoes/localizacao", json={
        "zona_id": cenario.zonas["D"], "justificativa": "x", "versao_esperada": 1})
    assert (resposta.status_code, resposta.json()["detail"]["codigo"]) == (
        404, "equipamento_inexistente")
    resposta = cenario.cliente.post("/equipamentos/999999/correcoes/cadastro", json={
        "nome": "Y", "justificativa": "x", "versao_esperada": 1})
    assert (resposta.status_code, resposta.json()["detail"]["codigo"]) == (
        404, "equipamento_inexistente")


@pytest.mark.parametrize("corpo", [
    {"justificativa": "   "},
    {"justificativa": None},
    {"justificativa": "x" * 1001},
    {"versao_esperada": 0},
    {"referencia": "r" * 256},
    {"extra": "campo desconhecido"},
], ids=["justificativa-vazia", "justificativa-ausente", "justificativa-longa", "versao-0",
        "referencia-longa", "campo-extra"])
def test_corpo_invalido_422_sem_gravar(engine, cenario, corpo):
    base = {"zona_id": cenario.zonas["D"], "justificativa": JUSTIFICATIVA,
            "versao_esperada": _versao(engine, cenario.equipamento_id)}
    base.update(corpo)
    if base["justificativa"] is None:
        del base["justificativa"]
    antes = _estado(engine, cenario.equipamento_id)

    for rota in ("localizacao", "cadastro"):
        payload = dict(base) if rota == "localizacao" else {
            **{k: v for k, v in base.items() if k != "zona_id"}, "nome": "Outro nome"}
        resposta = cenario.cliente.post(
            f"/equipamentos/{cenario.equipamento_id}/correcoes/{rota}", json=payload)
        assert resposta.status_code == 422, (rota, resposta.text)
    assert _estado(engine, cenario.equipamento_id) == antes


# --- conflito -------------------------------------------------------------------------


def test_versao_velha_409_com_versao_atual_sem_gravar(engine, cenario):
    versao = _versao(engine, cenario.equipamento_id)
    antes = _estado(engine, cenario.equipamento_id)

    resposta = _localizacao(cenario, cenario.zonas["D"], versao - 1 if versao > 1 else versao + 7)

    assert resposta.status_code == 409
    assert resposta.json()["detail"]["codigo"] == "conflito_de_versao"
    assert resposta.json()["detail"]["versao_atual"] == versao
    assert _estado(engine, cenario.equipamento_id) == antes


def test_patch_comum_incrementa_versao_e_invalida_correcao_pendente(engine, cenario):
    vista = _versao(engine, cenario.equipamento_id)
    _ok(cenario.cliente.patch(f"/equipamentos/{cenario.equipamento_id}",
                              json={"descricao": "outra"}), 200)
    assert _versao(engine, cenario.equipamento_id) == vista + 1

    for resposta in (_localizacao(cenario, cenario.zonas["D"], vista),
                     _cadastro(cenario, vista, identificador_interno="PAT-001-A")):
        assert (resposta.status_code, resposta.json()["detail"]["versao_atual"]) == (409, vista + 1)


def test_movimento_do_pipeline_depois_da_leitura_gera_conflito(engine, cenario):
    vista = _versao(engine, cenario.equipamento_id)
    _ok(_localizacao(cenario, cenario.zonas["C"], vista), 200)  # cria um movimento real
    vista = _versao(engine, cenario.equipamento_id)
    movimento = consultar(engine, "SELECT max(id) FROM historico_movimentacoes")[0][0]
    with engine.begin() as conexao:  # o pipeline move a projeção pelo mesmo ponto único
        location_repository.update_location(
            conexao, cenario.equipamento_id, zone_id=cenario.zonas["C"],
            movement_at=INICIO + timedelta(seconds=30), passage_id=None, movement_id=movimento)

    resposta = _localizacao(cenario, cenario.zonas["D"], vista)

    assert (resposta.status_code, resposta.json()["detail"]["versao_atual"]) == (409, vista + 1)


def test_duas_correcoes_simultaneas_exatamente_uma_vence(engine, cenario, api_auth):
    inserir_usuario(engine, "admin2@hupaa.example", perfil="administrador")
    outro = api_auth()
    assert logar(outro, "admin2@hupaa.example").status_code == 200
    versao = _versao(engine, cenario.equipamento_id)
    barreira = threading.Barrier(2)
    respostas = {}

    def corrigir(nome, cliente, zona):
        barreira.wait(10)
        respostas[nome] = cliente.post(
            f"/equipamentos/{cenario.equipamento_id}/correcoes/localizacao",
            json={"zona_id": zona, "justificativa": f"por {nome}", "versao_esperada": versao})

    threads = [threading.Thread(target=corrigir, args=args) for args in (
        ("admin", cenario.cliente, cenario.zonas["C"]), ("admin2", outro, cenario.zonas["D"]))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
        assert not thread.is_alive()

    assert sorted(r.status_code for r in respostas.values()) == [200, 409]
    assert consultar(engine, "SELECT count(*) FROM historico_movimentacoes")[0][0] == 1
    assert len(_auditorias(engine, "correcao_manual")) == 1


def test_stale_data_error_do_orm_vira_409(engine, cenario, monkeypatch):
    original = service_equipamento._validar_tipo_ativo

    def concorrente_no_meio(session, tipo_id):
        executar(engine, "UPDATE equipamentos SET versao = versao + 1 WHERE id = :id",
                 id=cenario.equipamento_id)
        return original(session, tipo_id)

    monkeypatch.setattr(service_equipamento, "_validar_tipo_ativo", concorrente_no_meio)
    resposta = cenario.cliente.patch(f"/equipamentos/{cenario.equipamento_id}",
                                     json={"tipo_id": cenario.tipos["Bomba"]})

    assert resposta.status_code == 409
    assert resposta.json()["detail"]["codigo"] == "conflito_de_versao"
    assert "Recarregue" in resposta.json()["detail"]["mensagem"]
    assert consultar(engine, "SELECT tipo_id FROM equipamentos WHERE id=:id",
                     id=cenario.equipamento_id) == [(cenario.tipos["Maca"],)]


@pytest.mark.parametrize("rota", ["localizacao", "cadastro"])
def test_correcao_espera_o_lock_e_depois_recusa_com_a_versao_nova(engine, cenario, rota):
    vista = _versao(engine, cenario.equipamento_id)
    antes = _estado(engine, cenario.equipamento_id)
    respostas = {}

    def corrigir():
        if rota == "localizacao":
            respostas["r"] = _localizacao(cenario, cenario.zonas["D"], vista)
        else:
            respostas["r"] = _cadastro(cenario, vista, identificador_interno="PAT-LOCK")

    conexao = engine.connect()
    transacao = conexao.begin()
    try:
        conexao.execute(text("SELECT id FROM equipamentos WHERE id = :id FOR UPDATE"),
                        {"id": cenario.equipamento_id})
        conexao.execute(text("UPDATE equipamentos SET versao = versao + 1 WHERE id = :id"),
                        {"id": cenario.equipamento_id})
        thread = threading.Thread(target=corrigir)
        thread.start()
        time.sleep(1)
        assert thread.is_alive(), "a correção deveria estar esperando o lock"
        transacao.commit()
    finally:
        if transacao.is_active:
            transacao.rollback()
        conexao.close()
    thread.join(30)
    assert not thread.is_alive()

    resposta = respostas["r"]
    assert (resposta.status_code, resposta.json()["detail"]["codigo"],
            resposta.json()["detail"]["versao_atual"]) == (409, "conflito_de_versao", vista + 1)
    depois = _estado(engine, cenario.equipamento_id)
    assert depois["historico"] == antes["historico"] and depois["auditoria"] == antes["auditoria"]
    assert depois["equipamento"][0][:-1] == antes["equipamento"][0][:-1]  # só a versão subiu


# --- rollback -------------------------------------------------------------------------


@pytest.mark.parametrize("quebrar", ["auditoria", "projecao"])
def test_falha_no_meio_nao_deixa_nada_gravado(engine, cenario, monkeypatch, quebrar):
    def falhar(*_args, **_kwargs):
        raise RuntimeError(f"falha simulada em {quebrar}")

    if quebrar == "auditoria":
        monkeypatch.setattr(auditoria, "registrar", falhar)
    else:
        monkeypatch.setattr(location_repository, "update_location", falhar)
    antes = _estado(engine, cenario.equipamento_id)

    with pytest.raises(RuntimeError, match="falha simulada"):
        _localizacao(cenario, cenario.zonas["D"], _versao(engine, cenario.equipamento_id))

    assert _estado(engine, cenario.equipamento_id) == antes


# --- autorização -------------------------------------------------------------------------


def test_operacional_403_anonimo_401_sem_gravar_e_negacao_auditada(engine, cenario, api_auth):
    inserir_usuario(engine, "op@hupaa.example")
    operadora, anonimo = api_auth(), api_auth()
    logar(operadora, "op@hupaa.example")
    versao = _versao(engine, cenario.equipamento_id)
    antes = _estado(engine, cenario.equipamento_id)
    corpos = {"localizacao": {"zona_id": cenario.zonas["D"]},
              "cadastro": {"identificador_interno": "PAT-HACK"}}

    for rota, corpo in corpos.items():
        url = f"/equipamentos/{cenario.equipamento_id}/correcoes/{rota}"
        payload = {**corpo, "justificativa": "x", "versao_esperada": versao}
        negado = operadora.post(url, json=payload)
        assert (negado.status_code, negado.json()) == (403, {"detail": "acesso_negado"})
        assert anonimo.post(url, json=payload).status_code == 401

    assert _estado(engine, cenario.equipamento_id) == antes
    negacoes = _auditorias(engine, "acesso_negado")
    assert [x["dados_depois"]["permissao"] for x in negacoes] == ["equipamentos:corrigir"] * 2
    assert {x["dados_depois"]["rota"] for x in negacoes} == {
        "/equipamentos/{equipamento_id}/correcoes/localizacao",
        "/equipamentos/{equipamento_id}/correcoes/cadastro"}


# --- cadastro ---------------------------------------------------------------------------


def test_correcao_de_cadastro_gera_uma_linha_e_patrimonio_novo_e_buscavel(engine, cenario):
    versao = _versao(engine, cenario.equipamento_id)
    historico_antes = consultar(engine, "SELECT count(*) FROM historico_movimentacoes")
    ultima = consultar(engine, "SELECT max(id) FROM auditorias")[0][0]

    corpo = _ok(_cadastro(cenario, versao, nome=" Maca 01-B ", identificador_interno=" PAT-101 ",
                          tipo_id=cenario.tipos["Bomba"], descricao="Bomba de infusão",
                          referencia=" CH-77 "), 200)

    assert (corpo["nome"], corpo["identificador_interno"], corpo["tipo_id"], corpo["descricao"],
            corpo["versao"]) == ("Maca 01-B", "PAT-101", cenario.tipos["Bomba"],
                                 "Bomba de infusão", versao + 1)
    novas = consultar(engine, "SELECT acao, usuario_id, origem, motivo, dados_antes, dados_depois "
                      "FROM auditorias WHERE id > :id", id=ultima)
    assert novas == [(
        "correcao_manual", cenario.admin_id, "usuario", "Patrimônio digitado errado no cadastro",
        {"nome": "Maca 01", "identificador_interno": "PAT-001", "tipo_id": cenario.tipos["Maca"],
         "descricao": "Maca de transporte"},
        {"nome": "Maca 01-B", "identificador_interno": "PAT-101",
         "tipo_id": cenario.tipos["Bomba"], "descricao": "Bomba de infusão",
         "referencia": "CH-77"},
    )]
    assert _ok(cenario.cliente.get("/equipamentos/por-identificador/pat-101"), 200)["id"] == (
        cenario.equipamento_id)
    busca = _ok(cenario.cliente.get("/api/ativos", params={"q": "PAT-101"}), 200)
    assert [item["id"] for item in busca["items"]] == [cenario.equipamento_id]
    assert consultar(engine, "SELECT count(*) FROM historico_movimentacoes") == historico_antes

    ultima = consultar(engine, "SELECT max(id) FROM auditorias")[0][0]
    _ok(cenario.cliente.patch(f"/equipamentos/{cenario.equipamento_id}", json={"nome": "Maca X"}),
        200)
    assert consultar(engine, "SELECT acao, motivo FROM auditorias WHERE id > :id", id=ultima) == [
        ("atualizar", None)]


def test_cadastro_descricao_null_limpa(engine, cenario):
    corpo = _ok(_cadastro(cenario, _versao(engine, cenario.equipamento_id), descricao=None), 200)

    assert corpo["descricao"] is None
    (linha,) = _auditorias(engine, "correcao_manual")
    assert (linha["dados_antes"], linha["dados_depois"]) == (
        {"descricao": "Maca de transporte"}, {"descricao": None})


@pytest.mark.parametrize(("campos", "status", "codigo"), [
    ({"versao_velha": True, "nome": "Novo"}, 409, "conflito_de_versao"),
    ({"identificador_interno": "pat-002"}, 409, "identificador_duplicado"),
    ({"nome": "Maca 01", "identificador_interno": "PAT-001"}, 422, "sem_mudanca"),
    ({}, 422, "sem_mudanca"),
    ({"tipo": "Antigo"}, 422, "tipo_invalido"),
    ({"tipo_id": 999_999}, 422, "tipo_invalido"),
], ids=["versao-velha", "patrimonio-de-outro", "sem-mudanca", "nada-informado", "tipo-inativo",
        "tipo-inexistente"])
def test_recusas_de_cadastro_nao_gravam_nada(engine, cenario, campos, status, codigo):
    campos = dict(campos)
    versao = _versao(engine, cenario.equipamento_id)
    if campos.pop("versao_velha", False):
        versao += 3
    if "tipo" in campos:
        campos["tipo_id"] = cenario.tipos[campos.pop("tipo")]
    antes = _estado(engine, cenario.equipamento_id)

    resposta = _cadastro(cenario, versao, **campos)

    assert (resposta.status_code, resposta.json()["detail"]["codigo"]) == (status, codigo), (
        resposta.text)
    assert _estado(engine, cenario.equipamento_id) == antes


# --- testes diretos ---------------------------------------------------------------------


def test_marca_de_correcao_nao_vaza_na_mesma_session(engine, cenario):
    with Session(bind=engine) as db:
        versao = _versao(engine, cenario.equipamento_id)
        with pytest.raises(service_correcoes.IdentificadorDuplicado):
            service_correcoes.corrigir_cadastro(
                db, equipamento_id=cenario.equipamento_id, justificativa="erro",
                referencia="R1", versao_esperada=versao, nome=None, tipo_id=None,
                identificador_interno="PAT-002", descricao=None, descricao_informada=False)
        service_correcoes.corrigir_cadastro(
            db, equipamento_id=cenario.equipamento_id, justificativa="certo", referencia=None,
            versao_esperada=versao, nome="Maca corrigida", tipo_id=None,
            identificador_interno=None, descricao=None, descricao_informada=False)
        ultima = consultar(engine, "SELECT max(id) FROM auditorias")[0][0]
        tipo = db.get(TipoEquipamento, cenario.tipos["Maca"])
        tipo.descricao = "mudança comum depois da correção"
        db.commit()

    assert consultar(engine, "SELECT acao, motivo, dados_depois FROM auditorias WHERE id > :id",
                     id=ultima) == [
        ("atualizar", None, {"descricao": "mudança comum depois da correção"})]
    assert [x["dados_depois"] for x in _auditorias(engine, "correcao_manual")] == [
        {"nome": "Maca corrigida"}]


def test_versao_nao_entra_na_auditoria_de_criacao(engine, cenario):
    (dados,) = consultar(engine, "SELECT dados_depois FROM auditorias WHERE acao = 'criar' "
                         "AND entidade = 'equipamentos' AND entidade_id = :id",
                         id=cenario.equipamento_id)[0]
    assert "versao" not in dados
    assert consultar(engine, "SELECT count(*) FROM auditorias WHERE dados_depois ? 'versao' "
                     "OR dados_antes ? 'versao'")[0][0] == 0


def test_resposta_de_equipamento_traz_versao_e_ultima_zona(engine, cenario):
    _ok(_localizacao(cenario, cenario.zonas["C"], _versao(engine, cenario.equipamento_id)), 200)

    corpo = _ok(cenario.cliente.get(f"/equipamentos/{cenario.equipamento_id}"), 200)

    assert (corpo["ultima_zona_id"], corpo["versao"]) == (
        cenario.zonas["C"], _versao(engine, cenario.equipamento_id))


def test_uso_interno_faz_strip_da_referencia_e_vazia_vira_null(engine, cenario):
    """Sem o schema da API no caminho, o próprio ledger normaliza a referência."""
    from rfid_location.service import LocationProjectionService

    servico = LocationProjectionService(engine)
    servico.apply_manual_location_correction(
        equipment_id=cenario.equipamento_id, destination_zone_id=cenario.zonas["C"],
        movimentada_em=INICIO, justificativa="interno", referencia="  OS-55  ")
    servico.apply_manual_location_correction(
        equipment_id=cenario.equipamento_id, destination_zone_id=cenario.zonas["D"],
        movimentada_em=INICIO + timedelta(minutes=1), justificativa="interno", referencia="   ")

    assert consultar(engine, "SELECT referencia FROM historico_movimentacoes ORDER BY id") == [
        ("OS-55",), (None,)]


# --- recarga pelo ID (revisão do PR #77) -----------------------------------------


def test_ativo_por_id_reflete_correcao_mesmo_fora_da_primeira_pagina_da_busca(cenario):
    """O painel recarrega por GET /api/ativos/{id}: depois de corrigir o patrimônio
    para "1", a busca textual paginada pode não trazer o equipamento; o ID sim."""
    cliente = cenario.cliente
    for numero in range(21):
        _ok(cliente.post("/equipamentos", json={
            "nome": f"Aaa {numero:02d}", "tipo_id": cenario.tipos["Bomba"],
            "identificador_interno": f"1-{numero:02d}"}))
    _ok(_localizacao(cenario, cenario.zonas["D"], _versao_api(cenario)))
    _ok(_cadastro(cenario, _versao_api(cenario), identificador_interno="1"))

    pagina = _ok(cliente.get("/api/ativos", params={"q": "1"}))
    assert pagina["total"] == 22
    assert cenario.equipamento_id not in [item["id"] for item in pagina["items"]]

    ativo = _ok(cliente.get(f"/api/ativos/{cenario.equipamento_id}"))
    assert (ativo["id"], ativo["identificador_interno"], ativo["ultima_zona"]["nome"]) == (
        cenario.equipamento_id, "1", "Zona D")
    assert ativo.keys() == pagina["items"][0].keys()  # mesmo formato da busca


def test_ativo_por_id_404_e_permissao_de_consulta(engine, cenario, api_auth):
    assert cenario.cliente.get("/api/ativos/999999").status_code == 404
    inserir_usuario(engine, "op-ativo@hupaa.example")
    operacional = api_auth()
    assert logar(operacional, "op-ativo@hupaa.example").status_code == 200
    assert operacional.get(f"/api/ativos/{cenario.equipamento_id}").status_code == 200
    assert api_auth().get(f"/api/ativos/{cenario.equipamento_id}").status_code == 401


def _versao_api(cenario) -> int:
    return _ok(cenario.cliente.get(f"/equipamentos/{cenario.equipamento_id}"))["versao"]
