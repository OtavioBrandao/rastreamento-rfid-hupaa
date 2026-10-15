"""
Trilha de auditoria imutável (ISS-028), contra Postgres real.

Login e cookie de verdade (`autenticacao_real`): o autor de cada linha é o
usuário da sessão, posto por `sessao_autenticada`. As fixtures `api_auth`,
`admin_logado` e `ajustes_auth` vêm do conftest; daqui só se importam helpers.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from suporte_auth import SENHA, consultar, executar, inserir_usuario, logar

from api import auditoria
from db.models import TipoEquipamento

pytestmark = pytest.mark.autenticacao_real

TEMP = "Temporaria-Audit-31"
COLUNAS = ("id", "usuario_id", "origem", "entidade", "entidade_id", "acao", "motivo",
           "correlation_id", "dados_antes", "dados_depois")


def _ultimo_id(engine) -> int:
    return consultar(engine, "SELECT coalesce(max(id), 0) FROM auditorias")[0][0]


def _linhas(engine, depois_de: int = 0) -> list[dict]:
    return [dict(zip(COLUNAS, linha)) for linha in consultar(
        engine, f"SELECT {', '.join(COLUNAS)} FROM auditorias WHERE id > :id ORDER BY id",
        id=depois_de)]


class Trilha:
    """Executa uma chamada e devolve só as linhas de auditoria que ela gerou."""

    def __init__(self, engine, cliente, autor_id: int) -> None:
        self.engine, self.cliente, self.autor_id = engine, cliente, autor_id

    def chamar(self, metodo: str, url: str, esperado: int, json=None):
        antes = _ultimo_id(self.engine)
        resposta = self.cliente.request(metodo, url, json=json)
        assert resposta.status_code == esperado, (url, resposta.text)
        novas = _linhas(self.engine, antes)
        correlacao = resposta.headers["x-correlation-id"]
        for linha in novas:
            assert (linha["usuario_id"], linha["origem"], linha["correlation_id"]) == (
                self.autor_id, "usuario", correlacao), linha
        return resposta, novas


def _acoes(linhas) -> Counter:
    return Counter((linha["entidade"], linha["acao"]) for linha in linhas)


@pytest.fixture
def trilha(engine, admin_logado) -> Trilha:
    cliente, admin_id = admin_logado
    return Trilha(engine, cliente, admin_id)


# --- completude pela API ----------------------------------------------------------


def test_cadastros_pela_api_geram_trilha_completa_com_autor_e_correlacao(trilha):
    t = trilha
    resposta, linhas = t.chamar("POST", "/tipos-equipamento", 201, {"nome": "Maca"})
    tipo_id = resposta.json()["id"]
    (linha,) = linhas
    assert (linha["entidade"], linha["acao"], linha["entidade_id"]) == (
        "tipos_equipamento", "criar", tipo_id)
    assert linha["dados_antes"] is None
    assert linha["dados_depois"] == {"nome": "Maca", "descricao": None, "ativo": True}

    _, linhas = t.chamar("PATCH", f"/tipos-equipamento/{tipo_id}", 200, {"nome": "Maca padrão"})
    assert [(x["acao"], x["dados_antes"], x["dados_depois"]) for x in linhas] == [
        ("atualizar", {"nome": "Maca"}, {"nome": "Maca padrão"})]

    resposta, linhas = t.chamar("POST", "/equipamentos", 201, {
        "nome": "Maca 01", "tipo_id": tipo_id, "identificador_interno": "PAT-001"})
    equipamento_id = resposta.json()["id"]
    (linha,) = linhas
    assert (linha["entidade"], linha["acao"]) == ("equipamentos", "criar")
    assert set(linha["dados_depois"]) == {
        "nome", "tipo_id", "identificador_interno", "descricao", "status"}
    for acao, rota in (("inativar", "inativar"), ("reativar", "reativar")):
        _, linhas = t.chamar("POST", f"/equipamentos/{equipamento_id}/{rota}", 200)
        assert [(x["entidade"], x["acao"]) for x in linhas] == [("equipamentos", acao)]

    _, linhas = t.chamar("POST", f"/equipamentos/{equipamento_id}/tag", 201, {"epc": "abcdef01"})
    (vinculo,) = linhas
    assert (vinculo["acao"], vinculo["dados_depois"]["epc"]) == ("vincular_epc", "ABCDEF01")
    assert vinculo["dados_depois"]["equipamento_id"] == equipamento_id

    _, linhas = t.chamar("PUT", f"/equipamentos/{equipamento_id}/tag", 200,
                         {"epc_novo": "11223344"})
    assert _acoes(linhas) == Counter({("associacoes_tag_equipamento", "desvincular_epc"): 1,
                                      ("associacoes_tag_equipamento", "vincular_epc"): 1})
    desv = next(x for x in linhas if x["acao"] == "desvincular_epc")
    assert desv["entidade_id"] == vinculo["entidade_id"]
    assert (desv["dados_antes"]["epc"], desv["dados_depois"]["epc"]) == ("ABCDEF01", "ABCDEF01")
    assert desv["dados_antes"]["fim"] is None and desv["dados_depois"]["fim"] is not None
    assert len({x["correlation_id"] for x in linhas}) == 1

    _, linhas = t.chamar("DELETE", f"/equipamentos/{equipamento_id}/tag", 200)
    assert [(x["acao"], x["dados_antes"]["epc"]) for x in linhas] == [
        ("desvincular_epc", "11223344")]

    resposta, linhas = t.chamar("POST", "/andares", 201, {"nome": "2º andar"})
    andar_id = resposta.json()["id"]
    assert _acoes(linhas) == Counter({("andares", "criar"): 1})
    resposta, linhas = t.chamar("POST", "/setores", 201, {"andar_id": andar_id, "nome": "Bloco B"})
    setor_id = resposta.json()["id"]
    assert _acoes(linhas) == Counter({("setores", "criar"): 1})
    zonas = []
    for nome in ("Zona 1", "Zona 2"):
        resposta, linhas = t.chamar("POST", "/zonas", 201, {"setor_id": setor_id, "nome": nome})
        zonas.append(resposta.json()["id"])
        assert _acoes(linhas) == Counter({("zonas", "criar"): 1})
    _, linhas = t.chamar("PATCH", f"/setores/{setor_id}", 200, {"nome": "Bloco C"})
    assert [(x["acao"], x["dados_antes"], x["dados_depois"]) for x in linhas] == [
        ("atualizar", {"nome": "Bloco B"}, {"nome": "Bloco C"})]

    resposta, linhas = t.chamar("POST", "/leitores", 201, {
        "reader_id": "reader-01", "fabricante": "Identix", "modelo": "EZ700",
        "identificador_serial": "SN-01"})
    leitor_id = resposta.json()["id"]
    (linha,) = linhas
    assert (linha["entidade"], linha["acao"]) == ("leitores", "criar")
    assert "status" not in linha["dados_depois"]
    assert "ultimo_heartbeat_em" not in linha["dados_depois"]

    resposta, linhas = t.chamar("POST", "/portais", 201, {
        "nome": "Portal 1", "zona_a_id": zonas[0], "zona_b_id": zonas[1]})
    portal_id = resposta.json()["id"]
    assert _acoes(linhas) == Counter({("portais", "criar"): 1})
    resposta, linhas = t.chamar("POST", "/antenas", 201, {
        "leitor_id": leitor_id, "porta_numero": 1, "zona_associada_id": zonas[0],
        "funcao": "entrada", "portal_id": portal_id})
    antena_id = resposta.json()["id"]
    assert _acoes(linhas) == Counter({("antenas", "criar"): 1})
    resposta, linhas = t.chamar("POST", f"/portais/{portal_id}/mapeamentos", 201, {
        "antena_id": antena_id, "lado": "a", "funcao": "entrada", "zona_id": zonas[0]})
    mapeamento_id = resposta.json()["id"]
    assert _acoes(linhas) == Counter({("mapeamentos_antena_portal", "criar"): 1})
    _, linhas = t.chamar("POST", f"/mapeamentos-antena/{mapeamento_id}/inativar", 200)
    assert [(x["entidade"], x["acao"]) for x in linhas] == [("mapeamentos_antena_portal", "inativar")]

    resposta, _ = t.chamar("POST", "/leitores", 201, {
        "reader_id": "reader-02", "fabricante": "Identix", "modelo": "EZ700",
        "identificador_serial": "SN-02"})
    leitor_livre = resposta.json()["id"]
    resposta, _ = t.chamar("POST", "/andares", 201, {"nome": "Andar vazio"})
    andar_vazio = resposta.json()["id"]
    for recurso, ident in (("leitores", leitor_livre), ("andares", andar_vazio)):
        for acao in ("inativar", "reativar"):
            _, linhas = t.chamar("POST", f"/{recurso}/{ident}/{acao}", 200)
            assert [(x["entidade"], x["acao"], x["dados_depois"]) for x in linhas] == [
                (recurso, acao, {"ativo": acao == "reativar"})]


def test_patch_sem_mudanca_nao_gera_linha(trilha):
    resposta, _ = trilha.chamar("POST", "/tipos-equipamento", 201, {"nome": "Cadeira"})

    _, linhas = trilha.chamar("PATCH", f"/tipos-equipamento/{resposta.json()['id']}", 200,
                              {"nome": "Cadeira"})

    assert linhas == []


def test_login_falho_e_aceito_nao_geram_usuario_alterado(engine, api_auth):
    inserir_usuario(engine, "maria@hupaa.example")
    antes = _ultimo_id(engine)

    logar(api_auth(), "maria@hupaa.example", "errada-123")
    logar(api_auth(), "maria@hupaa.example")

    assert [x["acao"] for x in _linhas(engine, antes)] == ["login_recusado", "login_aceito"]


# --- ORM direto: origem sistema --------------------------------------------------


def test_orm_direto_registra_valor_antigo_real_ignora_repeticao_e_exclui(engine, truncate_all):
    with Session(bind=engine) as db:
        tipo = TipoEquipamento(nome="Bomba", nome_normalizado="bomba")
        db.add(tipo)
        db.commit()  # expira todos os atributos
        tipo.nome = "Bomba de infusão"  # atributo expirado: o antes precisa ser real
        db.commit()
        tipo.nome = "Bomba de infusão"  # mesmo valor: nenhuma linha
        db.commit()
        db.delete(tipo)
        db.commit()

    linhas = _linhas(engine)
    assert [(x["acao"], x["dados_antes"], x["dados_depois"]) for x in linhas] == [
        ("criar", None, {"nome": "Bomba", "descricao": None, "ativo": True}),
        ("atualizar", {"nome": "Bomba"}, {"nome": "Bomba de infusão"}),
        ("excluir", {"nome": "Bomba de infusão", "descricao": None, "ativo": True}, None),
    ]
    assert {(x["origem"], x["usuario_id"]) for x in linhas} == {("sistema", None)}
    assert len({x["correlation_id"] for x in linhas}) == 1
    assert re.fullmatch(r"[0-9a-f]{32}", linhas[0]["correlation_id"])


# --- eventos de segurança ----------------------------------------------------------


def test_eventos_de_login_logout_e_acesso_negado(engine, api_auth):
    operadora = inserir_usuario(engine, "op@hupaa.example")
    antes = _ultimo_id(engine)

    logar(api_auth(), "ninguem@hupaa.example", "qualquer-123")
    cliente = api_auth()
    logar(cliente, "op@hupaa.example")
    negado = cliente.get("/usuarios")
    cliente.post("/auth/logout")

    linhas = _linhas(engine, antes)
    assert [x["acao"] for x in linhas] == [
        "login_recusado", "login_aceito", "acesso_negado", "logout"]
    recusado, aceito, acesso, saida = linhas
    assert (recusado["entidade"], recusado["entidade_id"], recusado["origem"],
            recusado["usuario_id"], recusado["motivo"]) == (
        "usuarios", None, "anonimo", None, "conta_inexistente")
    assert (aceito["usuario_id"], aceito["entidade_id"], aceito["origem"]) == (
        operadora, operadora, "usuario")
    assert (acesso["entidade"], acesso["usuario_id"], acesso["dados_depois"]) == (
        "rota", operadora,
        {"permissao": "usuarios:administrar", "metodo": "GET", "rota": "/usuarios"})
    assert acesso["correlation_id"] == negado.headers["x-correlation-id"]
    assert (saida["usuario_id"], saida["origem"]) == (operadora, "usuario")
    # Ausência é SQL NULL, não o literal JSON `null` (os dois viram None em Python).
    assert consultar(engine, "SELECT count(*) FROM auditorias WHERE "
                     "jsonb_typeof(dados_antes) = 'null' OR jsonb_typeof(dados_depois) = 'null'"
                     )[0][0] == 0
    assert consultar(engine, "SELECT dados_antes IS NULL, dados_depois IS NULL FROM auditorias "
                     "WHERE acao = 'login_aceito'") == [(True, True)]


def test_n_falhas_geram_n_recusas_anonimas_e_um_bloqueio(engine, api_auth, ajustes_auth):
    ajustes_auth.config = replace(ajustes_auth.config, login_max_tentativas=3)
    alvo = inserir_usuario(engine, "alvo@hupaa.example")
    antes = _ultimo_id(engine)

    for _ in range(3):
        logar(api_auth(), "alvo@hupaa.example", "errada-123")

    linhas = _linhas(engine, antes)
    assert Counter(x["acao"] for x in linhas) == Counter({"login_recusado": 3, "conta_bloqueada": 1})
    assert {(x["origem"], x["usuario_id"], x["entidade_id"]) for x in linhas} == {
        ("anonimo", None, alvo)}
    (bloqueio,) = [x for x in linhas if x["acao"] == "conta_bloqueada"]
    assert bloqueio["motivo"] == "tentativas_de_login"
    assert set(bloqueio["dados_depois"]) == {"bloqueado_ate"}


def test_bloqueio_na_troca_de_senha_tem_autor(engine, api_auth, ajustes_auth):
    ajustes_auth.config = replace(ajustes_auth.config, login_max_tentativas=2)
    usuario = inserir_usuario(engine, "maria@hupaa.example")
    cliente = api_auth()
    logar(cliente, "maria@hupaa.example")
    antes = _ultimo_id(engine)

    for _ in range(2):
        cliente.post("/auth/trocar-senha", json={"senha_atual": "errada-123",
                                                 "nova_senha": "nova-senha-123"})

    (bloqueio,) = _linhas(engine, antes)
    assert (bloqueio["acao"], bloqueio["usuario_id"], bloqueio["origem"],
            bloqueio["motivo"]) == (
        "conta_bloqueada", usuario, "usuario", "tentativas_de_troca_de_senha")
    assert set(bloqueio["dados_depois"]) == {"bloqueado_ate"}


# --- nenhum segredo -------------------------------------------------------------------


def test_trilha_inteira_sem_senha_hash_token_nem_email_digitado(engine, admin_logado, api_auth):
    cliente, _ = admin_logado
    criado = cliente.post("/usuarios", json={"nome": "João", "email": "joao@hupaa.example",
                                             "perfil": "operacional",
                                             "senha_temporaria": TEMP}).json()
    nova_temp = "Redefinida-Audit-42"
    cliente.post(f"/usuarios/{criado['id']}/redefinir-senha", json={"senha_temporaria": nova_temp})
    email_digitado = "Senha-No-Campo-Email-9"
    senha_digitada = "Digitada-Audit-77"
    logar(api_auth(), email_digitado, senha_digitada)
    logar(api_auth(), "joao@hupaa.example", senha_digitada)

    trilha = " ".join(linha[0] for linha in consultar(engine, "SELECT a::text FROM auditorias a"))
    hashes = [linha[0] for linha in consultar(engine, "SELECT senha_hash FROM usuarios")]
    tokens = [linha[0] for linha in consultar(engine, "SELECT token_hash FROM sessoes")]
    assert hashes and tokens
    for proibido in (SENHA, TEMP, nova_temp, senha_digitada, email_digitado,
                     email_digitado.lower(), "$argon2", "senha_hash", *hashes, *tokens):
        assert proibido not in trilha, proibido
    assert consultar(engine, "SELECT count(*) FROM auditorias "
                     "WHERE acao = 'alterar_senha' AND dados_depois->>'senha' = 'alterada'"
                     )[0][0] == 1


# --- imutabilidade e atomicidade ---------------------------------------------------------


def test_trilha_recusa_update_e_delete(engine, admin_logado):
    assert _linhas(engine)
    for sql in ("UPDATE auditorias SET motivo = 'adulterado'", "DELETE FROM auditorias"):
        with pytest.raises(DBAPIError, match="append-only"):
            executar(engine, sql)
    assert not consultar(engine, "SELECT 1 FROM auditorias WHERE motivo = 'adulterado'")


def test_falha_na_trilha_desfaz_a_operacao(engine, admin_logado, monkeypatch):
    cliente, _ = admin_logado
    antes = _ultimo_id(engine)

    def quebrar(_db):
        raise RuntimeError("trilha indisponível")

    monkeypatch.setattr(auditoria, "linhas_do_flush", quebrar)
    with pytest.raises(RuntimeError, match="trilha indisponível"):
        cliente.post("/tipos-equipamento", json={"nome": "Não persiste"})

    assert consultar(engine, "SELECT count(*) FROM tipos_equipamento")[0][0] == 0
    assert _linhas(engine, antes) == []


# --- consulta /auditorias -----------------------------------------------------------------


def test_consulta_filtra_pagina_ordena_e_traz_nome_do_autor(engine, admin_logado):
    cliente, admin_id = admin_logado
    tipos = [cliente.post("/tipos-equipamento", json={"nome": f"Tipo {i}"}).json()["id"]
             for i in range(3)]
    cliente.patch(f"/tipos-equipamento/{tipos[0]}", json={"nome": "Tipo zero"})

    todas = cliente.get("/auditorias", params={"entidade": "tipos_equipamento"}).json()
    assert set(todas) == {"items", "page", "size", "total", "pages"}
    assert (todas["total"], todas["size"], todas["pages"]) == (4, 50, 1)
    ids = [item["id"] for item in todas["items"]]
    assert ids == sorted(ids, reverse=True)
    assert {item["usuario_nome"] for item in todas["items"]} == {"admin"}

    pagina = cliente.get("/auditorias", params={
        "entidade": "tipos_equipamento", "size": 3, "page": 2}).json()
    assert ([item["id"] for item in pagina["items"]], pagina["pages"]) == ([ids[3]], 2)

    filtrada = cliente.get("/auditorias", params={
        "entidade": "tipos_equipamento", "entidade_id": tipos[0], "acao": "atualizar",
        "origem": "usuario", "usuario_id": admin_id}).json()
    assert [(i["acao"], i["dados_depois"]) for i in filtrada["items"]] == [
        ("atualizar", {"nome": "Tipo zero"})]
    correlacao = filtrada["items"][0]["correlation_id"]
    por_correlacao = cliente.get("/auditorias", params={"correlation_id": correlacao}).json()
    assert [i["id"] for i in por_correlacao["items"]] == [filtrada["items"][0]["id"]]

    detalhe = cliente.get(f"/auditorias/{ids[0]}")
    assert detalhe.status_code == 200 and detalhe.json() == todas["items"][0]
    assert cliente.get("/auditorias/999999").status_code == 404


def test_consulta_desde_inclusivo_e_ate_exclusivo(engine, admin_logado):
    cliente, _ = admin_logado
    for nome in ("A", "B", "C"):
        cliente.post("/tipos-equipamento", json={"nome": nome})
    registros = consultar(engine, "SELECT id, registrado_em FROM auditorias "
                          "WHERE entidade = 'tipos_equipamento' ORDER BY id")
    (_, primeiro), (meio_id, meio), (_, ultimo) = registros

    def ids(**params):
        resposta = cliente.get("/auditorias", params={"entidade": "tipos_equipamento", **params})
        return [item["id"] for item in resposta.json()["items"]]

    assert meio_id in ids(desde=meio.isoformat())
    assert meio_id not in ids(ate=meio.isoformat())
    assert ids(desde=meio.isoformat(), ate=ultimo.isoformat()) == [meio_id]


@pytest.mark.parametrize("params", [
    {"desde": "2026-09-28T12:00:00"},
    {"ate": "2026-09-28T12:00:00"},
    {"acao": "voar"},
    {"origem": "robo"},
    {"size": 201},
    {"page": 0},
])
def test_consulta_valida_parametros(admin_logado, params):
    cliente, _ = admin_logado
    assert cliente.get("/auditorias", params=params).status_code == 422


def test_consulta_exige_sessao_e_administrador(engine, api_auth):
    anonimo = api_auth()
    assert anonimo.get("/auditorias").status_code == 401
    assert anonimo.get("/auditorias/1").status_code == 401
    inserir_usuario(engine, "op@hupaa.example")
    operadora = api_auth()
    logar(operadora, "op@hupaa.example")
    for rota in ("/auditorias", "/auditorias/1"):
        resposta = operadora.get(rota)
        assert (resposta.status_code, resposta.json()) == (403, {"detail": "acesso_negado"})


# --- correlação ---------------------------------------------------------------------------


def test_correlation_id_do_cliente_aceito_malformado_trocado_e_sempre_no_header(
    engine, admin_logado, api_auth,
):
    cliente, _ = admin_logado
    resposta = cliente.post("/tipos-equipamento", json={"nome": "Correlacionado"},
                            headers={"X-Correlation-ID": "cliente-123.abc_X"})
    assert resposta.headers["x-correlation-id"] == "cliente-123.abc_X"
    assert consultar(engine, "SELECT correlation_id FROM auditorias "
                     "WHERE entidade = 'tipos_equipamento'") == [("cliente-123.abc_X",)]

    # Não-ASCII nem chega a sair do cliente HTTP; está no teste unitário abaixo.
    for malformado in ("tem espaco", "x" * 65, "barra/", ""):
        resposta = cliente.get("/auditorias", headers={"X-Correlation-ID": malformado})
        assert re.fullmatch(r"[0-9a-f]{32}", resposta.headers["x-correlation-id"]), malformado

    anonimo = api_auth().get("/auditorias", headers={"X-Correlation-ID": "anonimo-1"})
    assert (anonimo.status_code, anonimo.headers["x-correlation-id"]) == (401, "anonimo-1")
    assert re.fullmatch(r"[0-9a-f]{32}", api_auth().get("/health").headers["x-correlation-id"])


def test_correlation_id_valido_unidade():
    assert auditoria.correlation_id_valido("abc-1.2_3") == "abc-1.2_3"
    assert auditoria.correlation_id_valido("a" * 64) == "a" * 64
    for invalido in (None, "", "a" * 65, "com espaço", "barra/", "ç"):
        assert re.fullmatch(r"[0-9a-f]{32}", auditoria.correlation_id_valido(invalido))


def test_tabelas_auditadas_e_campos_excluidos():
    assert auditoria.TABELAS_AUDITADAS == {
        "tipos_equipamento", "equipamentos", "associacoes_tag_equipamento", "andares",
        "setores", "zonas", "leitores", "antenas", "portais", "mapeamentos_antena_portal",
        "usuarios"}
    assert {"senha_hash", "tentativas_falhas", "bloqueado_ate", "ultimo_login_em"} <= (
        auditoria.CAMPOS_FORA_POR_TABELA["usuarios"])
    assert {"status", "ultimo_heartbeat_em"} <= auditoria.CAMPOS_FORA_POR_TABELA["leitores"]
