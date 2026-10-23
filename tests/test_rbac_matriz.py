"""
Matriz de permissões (ISS-027) contra a API real, com login e cookie de verdade.

A REGRA esperada aqui foi escrita a partir das decisões da issue, não do
código de `api/permissoes.py`:
- públicas: GET /health, POST /auth/login, POST /auth/logout;
- qualquer sessão (inclusive senha temporária): GET /auth/me, POST /auth/trocar-senha;
- operacional CONSULTA tudo (GET), exceto usuários e a trilha de auditoria (ISS-028), e não altera nada;
  hardware/topologia e leituras do laboratório incluídos na consulta;
- administrador faz tudo.

As rotas são DESCOBERTAS por introspecção: rota nova sem permissão declarada
derruba `test_toda_rota_nao_publica_declara_permissao`.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator

import pytest
from conftest import TABELAS_DO_CRUD
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session
from suporte_auth import BASE_URL, SENHA, consultar, executar, inserir_usuario, logar

from api.database import get_db
from api.dependencias_auth import sessao_autenticada
from api.main import app

pytestmark = pytest.mark.autenticacao_real

PUBLICAS = {("GET", "/health"), ("POST", "/auth/login"), ("POST", "/auth/logout")}
QUALQUER_SESSAO = {("GET", "/auth/me"), ("POST", "/auth/trocar-senha")}
METODOS_DE_CONSULTA = {"GET", "HEAD", "OPTIONS"}

# Recurso esperado por prefixo de caminho, a partir das decisões da issue.
RECURSO_POR_PREFIXO = [
    ("/api/laboratorio", "laboratorio"),
    # Presença por leitura bruta (página Leituras): mesma permissão das leituras do laboratório.
    ("/api/leituras", "laboratorio"),
    ("/api/ativos", "equipamentos"),
    # Cadastro pelo dashboard (manual e por EPC detectado): mesmo recurso de equipamentos.
    ("/api/cadastro", "equipamentos"),
    # Simulador web: consulta para todos; configurar e mover itens, só administrador.
    ("/api/simulacao", "simulacao"),
    ("/api/dashboard", "equipamentos"),
    ("/equipamentos", "equipamentos"),
    ("/tipos-equipamento", "equipamentos"),
    ("/tags", "equipamentos"),
    ("/localizacoes", "localizacao"),
    ("/andares", "localizacao"),
    ("/setores", "localizacao"),
    ("/zonas", "localizacao"),
    ("/leitores", "hardware"),
    ("/antenas", "hardware"),
    ("/portais", "hardware"),
    ("/mapeamentos-antena", "hardware"),
    ("/usuarios", "usuarios"),
    ("/auditorias", "auditoria"),  # ISS-028: consulta da trilha, só administrador
]

PERMISSOES_OPERACIONAL = [
    "equipamentos:consultar", "hardware:consultar", "laboratorio:consultar",
    "localizacao:consultar", "simulacao:consultar",
]
PERMISSOES_ADMINISTRADOR = sorted([
    "equipamentos:consultar", "equipamentos:alterar", "localizacao:consultar",
    "localizacao:alterar", "hardware:consultar", "hardware:alterar",
    "laboratorio:consultar", "usuarios:administrar", "auditoria:consultar",
    "equipamentos:corrigir", "simulacao:consultar", "simulacao:alterar",
])


# --- descoberta ---------------------------------------------------------------


def _rotas(rotas, prefixo: str = "") -> Iterator[tuple[str, APIRoute]]:
    for rota in rotas:
        if isinstance(rota, APIRoute):
            yield prefixo + rota.path, rota
        elif hasattr(rota, "original_router"):  # `_IncludedRouter` desta versão do FastAPI
            yield from _rotas(rota.original_router.routes,
                              prefixo + rota.include_context.prefix)


def descobrir_rotas() -> list[tuple[str, str, APIRoute]]:
    return sorted(
        (metodo, caminho, rota)
        for caminho, rota in _rotas(app.routes)
        for metodo in rota.methods
    )


ROTAS = descobrir_rotas()
IDS_ROTAS = [f"{metodo} {caminho}" for metodo, caminho, _ in ROTAS]


def _dependencias(dependant) -> Iterator:
    for sub in dependant.dependencies:
        yield sub.call
        yield from _dependencias(sub)


def permissoes_declaradas(metodo: str, rota: APIRoute) -> set[str]:
    declaradas = set()
    for chamada in _dependencias(rota.dependant):
        if hasattr(chamada, "permissao_consulta"):
            declaradas.add(chamada.permissao_consulta.value if metodo in METODOS_DE_CONSULTA
                           else chamada.permissao_alteracao.value)
        elif hasattr(chamada, "permissoes_exigidas"):
            declaradas |= {permissao.value for permissao in chamada.permissoes_exigidas}
    return declaradas


def recurso_esperado(caminho: str) -> str:
    for prefixo, recurso in RECURSO_POR_PREFIXO:
        if caminho == prefixo or caminho.startswith(prefixo + "/"):
            return recurso
    raise AssertionError(f"rota sem recurso nas decisões: {caminho}")


def operacional_pode(metodo: str, caminho: str) -> bool:
    return (metodo in METODOS_DE_CONSULTA
            and recurso_esperado(caminho) not in {"usuarios", "auditoria"})


def test_descoberta_encontra_todas_as_rotas():
    # Sem isto, uma descoberta quebrada deixaria a matriz passar vazia.
    assert len(ROTAS) >= 80
    assert ("GET", "/equipamentos") in {(m, c) for m, c, _ in ROTAS}
    assert ("POST", "/usuarios/{usuario_id}/redefinir-senha") in {(m, c) for m, c, _ in ROTAS}


def test_toda_rota_nao_publica_declara_permissao():
    sem_permissao = []
    for metodo, caminho, rota in ROTAS:
        if (metodo, caminho) in PUBLICAS:
            continue
        if (metodo, caminho) in QUALQUER_SESSAO:
            if sessao_autenticada not in set(_dependencias(rota.dependant)):
                sem_permissao.append(f"{metodo} {caminho} (sem sessão)")
            continue
        if not permissoes_declaradas(metodo, rota):
            sem_permissao.append(f"{metodo} {caminho}")
    assert sem_permissao == [], "rotas sem permissão declarada:\n" + "\n".join(sem_permissao)


@pytest.mark.parametrize(("metodo", "caminho", "rota"), ROTAS, ids=IDS_ROTAS)
def test_permissao_declarada_bate_com_as_decisoes(metodo, caminho, rota):
    if (metodo, caminho) in PUBLICAS | QUALQUER_SESSAO:
        return
    recurso = recurso_esperado(caminho)
    if "/correcoes/" in caminho:
        # ISS-025: correção manual é permissão própria, só do administrador.
        esperada = {"equipamentos:corrigir"}
    elif recurso == "usuarios":
        esperada = {"usuarios:administrar"}
    elif recurso == "auditoria":
        esperada = {"auditoria:consultar"}
    elif metodo in METODOS_DE_CONSULTA:
        esperada = {f"{recurso}:consultar"}
    else:
        # Laboratório só tem leitura; a escrita (se existir) é de hardware.
        esperada = {"hardware:alterar" if recurso == "laboratorio" else f"{recurso}:alterar"}
    assert permissoes_declaradas(metodo, rota) == esperada


# --- sessões reais compartilhadas pelo módulo -----------------------------------


def _limpar(engine) -> None:
    with engine.begin() as conexao:
        conexao.execute(text(
            "TRUNCATE TABLE " + ", ".join(TABELAS_DO_CRUD) + " RESTART IDENTITY CASCADE"
        ))


@pytest.fixture(scope="module")
def perfis_logados(engine):
    """Um cliente anônimo, um operacional e um administrador, logados uma vez só."""
    _limpar(engine)

    def get_db_de_teste():
        session = Session(bind=engine)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = get_db_de_teste
    ids = {
        "operacional": inserir_usuario(engine, "operadora@hupaa.example"),
        "administrador": inserir_usuario(engine, "admin@hupaa.example", perfil="administrador"),
    }
    clientes = {"anonimo": TestClient(app, base_url=BASE_URL)}
    for perfil, email in (("operacional", "operadora@hupaa.example"),
                          ("administrador", "admin@hupaa.example")):
        cliente = TestClient(app, base_url=BASE_URL)
        assert logar(cliente, email).status_code == 200
        clientes[perfil] = cliente
    try:
        yield clientes, ids
    finally:
        for cliente in clientes.values():
            cliente.close()
        app.dependency_overrides.pop(get_db, None)
        _limpar(engine)


def _url(caminho: str) -> str:
    def valor(parametro: re.Match) -> str:
        nome = parametro.group(1)
        if nome == "epc":
            return "E28011700000020000000999"
        if nome == "identificador_interno":
            return "PAT-INEXISTENTE"
        return "999999"
    return re.sub(r"\{([^}]+)\}", valor, caminho)


def _chamar(cliente: TestClient, metodo: str, caminho: str, **kwargs):
    if metodo in {"POST", "PUT", "PATCH"}:
        kwargs.setdefault("json", {})
    return cliente.request(metodo, _url(caminho), **kwargs)


ROTAS_EXERCITADAS = [
    (metodo, caminho) for metodo, caminho, _ in ROTAS if (metodo, caminho) != ("POST", "/auth/logout")
]


@pytest.mark.parametrize(("metodo", "caminho"), ROTAS_EXERCITADAS,
                         ids=[f"{m} {c}" for m, c in ROTAS_EXERCITADAS])
def test_cada_rota_respeita_a_regra_para_os_tres_perfis(perfis_logados, metodo, caminho):
    clientes, _ids = perfis_logados
    publica = (metodo, caminho) in PUBLICAS
    qualquer_sessao = (metodo, caminho) in QUALQUER_SESSAO

    anonimo = _chamar(clientes["anonimo"], metodo, caminho)
    if publica:
        assert anonimo.status_code not in (401, 403), anonimo.text
    else:
        assert (anonimo.status_code, anonimo.json()) == (401, {"detail": "nao_autenticado"})

    operacional = _chamar(clientes["operacional"], metodo, caminho)
    if publica or qualquer_sessao or operacional_pode(metodo, caminho):
        assert operacional.status_code not in (401, 403), operacional.text
    else:
        assert (operacional.status_code, operacional.json()) == (
            403, {"detail": "acesso_negado"})

    administrador = _chamar(clientes["administrador"], metodo, caminho)
    assert administrador.status_code not in (401, 403), administrador.text


# --- negação sem efeito, perfis especiais, /auth/me, logs ------------------------


def test_negacao_nao_altera_dados(engine, perfis_logados):
    clientes, _ = perfis_logados
    operacional, administrador = clientes["operacional"], clientes["administrador"]
    tipo = administrador.post("/tipos-equipamento", json={"nome": "Maca RBAC"}).json()
    antes = {
        "tipos": consultar(engine, "SELECT id, nome, ativo FROM tipos_equipamento ORDER BY id"),
        "equipamentos": consultar(engine, "SELECT count(*) FROM equipamentos"),
        "usuarios": consultar(engine, "SELECT id, nome, perfil_id, ativo FROM usuarios ORDER BY id"),
    }
    tentativas = [
        ("POST", "/tipos-equipamento", {"nome": "Criado pela operadora"}),
        ("PATCH", f"/tipos-equipamento/{tipo['id']}", {"nome": "Renomeado"}),
        ("POST", f"/tipos-equipamento/{tipo['id']}/inativar", None),
        ("POST", "/equipamentos", {"nome": "Bomba", "tipo_id": tipo["id"],
                                   "identificador_interno": "PAT-RBAC-1"}),
        ("POST", "/usuarios", {"nome": "Intrusa", "email": "intrusa@hupaa.example",
                               "perfil": "administrador", "senha_temporaria": "temporaria-1"}),
    ]
    for metodo, caminho, corpo in tentativas:
        resposta = operacional.request(metodo, caminho, json=corpo)
        assert (resposta.status_code, resposta.json()) == (403, {"detail": "acesso_negado"})

    depois = {
        "tipos": consultar(engine, "SELECT id, nome, ativo FROM tipos_equipamento ORDER BY id"),
        "equipamentos": consultar(engine, "SELECT count(*) FROM equipamentos"),
        "usuarios": consultar(engine, "SELECT id, nome, perfil_id, ativo FROM usuarios ORDER BY id"),
    }
    assert depois == antes


def test_senha_temporaria_bloqueia_ate_a_consulta(engine, perfis_logados):
    inserir_usuario(engine, "temporaria@hupaa.example", deve_trocar_senha=True)
    with TestClient(app, base_url=BASE_URL) as cliente:
        assert logar(cliente, "temporaria@hupaa.example").status_code == 200
        for caminho in ("/equipamentos", "/api/ativos", "/leitores", "/api/laboratorio/leituras"):
            resposta = cliente.get(caminho)
            assert (resposta.status_code, resposta.json()) == (
                403, {"detail": "troca_de_senha_obrigatoria"}), caminho
        assert cliente.get("/auth/me").status_code == 200


def test_perfil_fora_da_matriz_nao_tem_permissao_nenhuma(engine, perfis_logados):
    executar(engine, "INSERT INTO perfis (nome) VALUES ('auditor') ON CONFLICT (nome) DO NOTHING")
    usuario_id = inserir_usuario(engine, "auditora@hupaa.example", perfil="auditor")
    try:
        with TestClient(app, base_url=BASE_URL) as cliente:
            login = logar(cliente, "auditora@hupaa.example")
            assert login.status_code == 200, login.text
            assert login.json()["permissoes"] == []
            assert login.json()["usuario"]["perfil"] == "auditor"
            me = cliente.get("/auth/me")
            assert (me.status_code, me.json()["permissoes"]) == (200, [])
            for metodo, caminho in (("GET", "/equipamentos"), ("GET", "/leitores"),
                                    ("GET", "/api/laboratorio/leituras"), ("GET", "/usuarios"),
                                    ("POST", "/tipos-equipamento")):
                resposta = _chamar(cliente, metodo, caminho)
                assert (resposta.status_code, resposta.json()) == (
                    403, {"detail": "acesso_negado"}), caminho
    finally:
        # A trilha (append-only) referencia a usuária: só TRUNCATE a limpa. As
        # sessões são só as DELA — o módulo compartilha sessões logadas.
        executar(engine, "TRUNCATE TABLE auditorias")
        executar(engine, "DELETE FROM sessoes WHERE usuario_id = :id", id=usuario_id)
        executar(engine, "DELETE FROM usuarios WHERE id = :id", id=usuario_id)
        executar(engine, "DELETE FROM perfis WHERE nome = 'auditor'")


def test_me_e_login_devolvem_as_permissoes_de_cada_perfil(perfis_logados):
    clientes, _ = perfis_logados

    assert clientes["operacional"].get("/auth/me").json()["permissoes"] == PERMISSOES_OPERACIONAL
    assert clientes["administrador"].get("/auth/me").json()["permissoes"] == (
        PERMISSOES_ADMINISTRADOR)
    with TestClient(app, base_url=BASE_URL) as outro:
        assert logar(outro, "operadora@hupaa.example").json()["permissoes"] == (
            PERMISSOES_OPERACIONAL)


def test_log_de_negacao_tem_os_campos_certos_e_nenhum_segredo(perfis_logados, caplog):
    clientes, ids = perfis_logados
    operacional = clientes["operacional"]
    token = operacional.cookies.get("rfid_sessao")
    marcador_corpo = "corpo-secreto-rbac-4471"
    caplog.set_level(logging.INFO, logger="api")

    operacional.post("/equipamentos/999999/inativar", json={"x": marcador_corpo})
    clientes["anonimo"].post("/tipos-equipamento", json={"nome": marcador_corpo})  # 401

    eventos = [json.loads(r.getMessage()) for r in caplog.records
               if r.name == "api.autorizacao"]
    assert eventos == [{
        "evento": "acesso_negado",
        "usuario_id": ids["operacional"],
        "perfil": "operacional",
        "permissao": "equipamentos:alterar",
        "metodo": "POST",
        "rota": "/equipamentos/{equipamento_id}/inativar",
    }]
    # Só os loggers da aplicação: o do httpx (cliente de teste) loga a URL.
    texto = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("api"))
    for proibido in (token, marcador_corpo, SENHA, "rfid_sessao", "999999"):
        assert proibido not in texto


def test_consulta_permitida_nao_gera_log_de_autorizacao(perfis_logados, caplog):
    clientes, _ = perfis_logados
    caplog.set_level(logging.INFO, logger="api")

    assert clientes["operacional"].get("/equipamentos").status_code == 200
    assert clientes["administrador"].post("/equipamentos/999999/inativar").status_code == 404

    assert [r for r in caplog.records if r.name == "api.autorizacao"] == []
