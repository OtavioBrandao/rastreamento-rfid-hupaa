"""
Contrato HTTP da autenticação (ISS-026): login, cookie, sessão, logout,
bloqueio, senha temporária, troca de senha, 422 sem eco e logs.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import replace
from datetime import timedelta

import pytest
from argon2 import PasswordHasher, extract_parameters
from argon2.low_level import Type
from suporte_auth import (
    INICIO,
    SENHA,
    cliente_com_token,
    consultar,
    executar,
    inserir_usuario,
    logar,
)

from api import senhas

# ISS-027: login e cookie reais; sem o administrador de teste do conftest.
pytestmark = pytest.mark.autenticacao_real

EMAIL = "maria@hupaa.example"
NOVA = "nova-senha-segura-2"


def _set_cookie(resposta) -> str:
    cabecalhos = resposta.headers.get_list("set-cookie")
    assert len(cabecalhos) == 1, cabecalhos
    return cabecalhos[0]


# --- login e cookie -----------------------------------------------------------


def test_login_define_cookie_opaco_com_todas_as_flags(engine, api_auth):
    usuario_id = inserir_usuario(engine, EMAIL)
    cliente = api_auth()

    resposta = logar(cliente, EMAIL)

    assert resposta.status_code == 200
    cookie = _set_cookie(resposta)
    partes = [parte.strip() for parte in cookie.split(";")]
    nome, token = partes[0].split("=", 1)
    atributos = {parte.lower() for parte in partes[1:]}
    assert nome == "rfid_sessao"
    assert {"httponly", "secure", "samesite=strict", "path=/", "max-age=28800"} <= atributos
    assert len(token) >= 43  # 32 bytes em base64url
    assert resposta.headers["cache-control"] == "no-store"
    corpo = resposta.json()
    assert corpo["usuario"]["id"] == usuario_id
    assert corpo["usuario"]["perfil"] == "operacional"
    assert corpo["sessao_expira_em"] == "2026-09-28T20:00:00Z"
    assert token not in resposta.text


def test_cookie_sem_secure_quando_configurado(engine, api_auth, ajustes_auth):
    ajustes_auth.config = replace(ajustes_auth.config, cookie_seguro=False)
    inserir_usuario(engine, EMAIL)

    cookie = _set_cookie(logar(api_auth(), EMAIL)).lower()

    assert "secure" not in cookie
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_banco_guarda_so_hash_do_token_e_da_senha(engine, api_auth):
    inserir_usuario(engine, EMAIL)
    cliente = api_auth()
    logar(cliente, EMAIL)
    token = cliente.cookies.get("rfid_sessao")

    (token_hash,) = consultar(engine, "SELECT token_hash FROM sessoes")[0]
    assert token_hash == hashlib.sha256(token.encode()).hexdigest()
    despejo = json.dumps([
        [str(valor) for valor in linha]
        for tabela in ("sessoes", "usuarios", "auditorias")
        for linha in consultar(engine, f"SELECT * FROM {tabela}")
    ])
    assert token not in despejo
    assert SENHA not in despejo
    (senha_hash,) = consultar(engine, "SELECT senha_hash FROM usuarios")[0]
    assert extract_parameters(senha_hash).type is Type.ID


def test_email_do_login_e_normalizado(engine, api_auth):
    inserir_usuario(engine, EMAIL)

    assert logar(api_auth(), "  Maria@HUPAA.Example ").status_code == 200


def test_authorization_header_nao_substitui_cookie(engine, api_auth):
    inserir_usuario(engine, EMAIL)
    cliente = api_auth()
    logar(cliente, EMAIL)
    token = cliente.cookies.get("rfid_sessao")

    anonimo = api_auth()
    resposta = anonimo.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert resposta.status_code == 401
    assert resposta.json() == {"detail": "nao_autenticado"}


# --- login recusado -----------------------------------------------------------


@pytest.fixture
def espiao_argon2(monkeypatch):
    """Conta chamadas a `senhas.verificar_senha` e guarda o hash usado."""
    chamadas: list[str] = []
    original = senhas.verificar_senha

    def espiao(hash_armazenado, senha):
        chamadas.append(hash_armazenado)
        return original(hash_armazenado, senha)

    monkeypatch.setattr(senhas, "verificar_senha", espiao)
    return chamadas


def _preparar_motivo(engine, motivo: str) -> tuple[str, str]:
    if motivo == "senha_incorreta":
        inserir_usuario(engine, EMAIL)
        return EMAIL, "senha-errada-9"
    if motivo == "conta_inexistente":
        return "ninguem@hupaa.example", SENHA
    if motivo == "conta_inativa":
        inserir_usuario(engine, EMAIL, ativo=False)
        return EMAIL, SENHA
    usuario_id = inserir_usuario(engine, EMAIL)
    executar(engine, "UPDATE usuarios SET bloqueado_ate = :ate WHERE id = :id",
             ate=INICIO + timedelta(minutes=5), id=usuario_id)
    return EMAIL, SENHA


MOTIVOS = ("senha_incorreta", "conta_inexistente", "conta_inativa", "conta_bloqueada")


@pytest.mark.parametrize("motivo", MOTIVOS)
def test_login_recusado_tem_resposta_unica_e_uma_verificacao_argon2(
    engine, api_auth, espiao_argon2, motivo,
):
    email, senha = _preparar_motivo(engine, motivo)
    cliente = api_auth()

    resposta = logar(cliente, email, senha)

    assert resposta.status_code == 401
    assert resposta.json() == {"detail": "credenciais_invalidas"}
    assert "set-cookie" not in resposta.headers
    assert len(espiao_argon2) == 1
    # Verificação COMPLETA: o hash usado é Argon2id legível (real ou fictício).
    assert extract_parameters(espiao_argon2[0]).type is Type.ID
    assert consultar(engine, "SELECT count(*) FROM sessoes")[0][0] == 0


def test_quatro_motivos_produzem_respostas_identicas(engine, api_auth):
    respostas = []
    for motivo in MOTIVOS:
        executar(engine, "TRUNCATE usuarios, sessoes, auditorias RESTART IDENTITY")
        email, senha = _preparar_motivo(engine, motivo)
        resposta = logar(api_auth(), email, senha)
        respostas.append((resposta.status_code, resposta.text,
                          sorted(k for k in resposta.headers if k != "content-length")))
    assert len(set(map(str, respostas))) == 1


def test_login_nao_valida_formato_do_email(engine, api_auth):
    resposta = logar(api_auth(), "isto nao e email", SENHA)

    assert resposta.status_code == 401
    assert resposta.json() == {"detail": "credenciais_invalidas"}


@pytest.mark.parametrize(
    "hash_armazenado",
    [
        "$2b$12$KbQiTBn8lh0mD0xGGlO2UuB2bYh0x7xqSbq5WnS1ZC7iD9j8m5T4e",  # bcrypt legado
        SENHA,  # texto puro
        "",
        "$argon2id$v=19$quebrado",
        PasswordHasher(type=Type.I).hash(SENHA),  # Argon2i com a senha CERTA
        # Parâmetros legíveis (passam pelo filtro), corpo inválido: o verify levanta.
        PasswordHasher().hash(SENHA).rsplit("$", 2)[0] + "$!!!!$!!!!",
        PasswordHasher().hash(SENHA)[:-5],
    ],
    ids=["bcrypt", "texto-puro", "vazio", "argon2id-truncado", "argon2i",
         "argon2id-corpo-invalido", "argon2id-sem-final"],
)
def test_hash_ilegivel_ou_legado_recusa_sem_500(engine, api_auth, hash_armazenado):
    usuario_id = inserir_usuario(engine, EMAIL, senha_hash=hash_armazenado)

    resposta = logar(api_auth(), EMAIL, SENHA)

    assert resposta.status_code == 401
    assert resposta.json() == {"detail": "credenciais_invalidas"}
    assert consultar(engine, "SELECT tentativas_falhas FROM usuarios WHERE id = :id",
                     id=usuario_id)[0][0] == 1


def test_login_valida_tamanho_sem_ecoar_senha(api_auth):
    senha_longa = "segredo-" + "x" * 1100

    resposta = api_auth().post("/auth/login", json={"email": EMAIL, "senha": senha_longa})

    assert resposta.status_code == 422
    assert "segredo-" not in resposta.text


# --- bloqueio -----------------------------------------------------------------


def test_bloqueio_apos_n_falhas_seguidas_e_liberacao_no_prazo(
    engine, api_auth, relogio, ajustes_auth,
):
    ajustes_auth.config = replace(ajustes_auth.config, login_max_tentativas=3,
                                  login_bloqueio=timedelta(minutes=15))
    usuario_id = inserir_usuario(engine, EMAIL)
    cliente = api_auth()

    for _ in range(3):
        assert logar(cliente, EMAIL, "errada-123").status_code == 401

    tentativas, bloqueado_ate = consultar(
        engine, "SELECT tentativas_falhas, bloqueado_ate FROM usuarios WHERE id=:id",
        id=usuario_id)[0]
    assert tentativas == 0
    assert bloqueado_ate == INICIO + timedelta(minutes=15)
    # Durante o bloqueio nem a senha certa entra.
    assert logar(cliente, EMAIL).status_code == 401
    relogio.avancar(minutes=14, seconds=59)
    assert logar(cliente, EMAIL).status_code == 401
    relogio.avancar(seconds=1)  # exatamente em bloqueado_ate: liberado
    resposta = logar(cliente, EMAIL)
    assert resposta.status_code == 200
    assert consultar(engine, "SELECT bloqueado_ate FROM usuarios WHERE id=:id",
                     id=usuario_id)[0][0] is None


def test_falhas_durante_bloqueio_nao_contam_nem_estendem(engine, api_auth, ajustes_auth):
    ajustes_auth.config = replace(ajustes_auth.config, login_max_tentativas=2)
    usuario_id = inserir_usuario(engine, EMAIL)
    cliente = api_auth()
    for _ in range(2):
        logar(cliente, EMAIL, "errada-123")
    antes = consultar(engine, "SELECT bloqueado_ate FROM usuarios WHERE id=:id", id=usuario_id)

    for _ in range(3):
        logar(cliente, EMAIL, "errada-123")

    assert consultar(engine, "SELECT bloqueado_ate, tentativas_falhas FROM usuarios "
                     "WHERE id=:id", id=usuario_id)[0] == (antes[0][0], 0)


def test_sucesso_zera_as_falhas_seguidas(engine, api_auth, ajustes_auth):
    ajustes_auth.config = replace(ajustes_auth.config, login_max_tentativas=3)
    usuario_id = inserir_usuario(engine, EMAIL)
    cliente = api_auth()

    for senha in ("errada-1x", "errada-2x", SENHA, "errada-3x", "errada-4x"):
        logar(cliente, EMAIL, senha)

    assert consultar(engine, "SELECT tentativas_falhas, bloqueado_ate FROM usuarios "
                     "WHERE id=:id", id=usuario_id)[0] == (2, None)


# --- sessão ------------------------------------------------------------------


def test_sessao_expira_na_duracao_configurada(engine, api_auth, relogio):
    inserir_usuario(engine, EMAIL)
    cliente = api_auth()
    logar(cliente, EMAIL)

    relogio.avancar(minutes=479, seconds=59)
    assert cliente.get("/auth/me").status_code == 200
    relogio.avancar(seconds=1)
    resposta = cliente.get("/auth/me")
    assert resposta.status_code == 401
    assert resposta.json() == {"detail": "nao_autenticado"}


def test_sem_cookie_ou_token_desconhecido_401(api_auth):
    assert api_auth().get("/auth/me").status_code == 401
    assert cliente_com_token("token-inventado").get("/auth/me").status_code == 401


def test_logout_revoga_apaga_cookie_e_token_reapresentado_falha(engine, api_auth):
    inserir_usuario(engine, EMAIL)
    cliente = api_auth()
    logar(cliente, EMAIL)
    token = cliente.cookies.get("rfid_sessao")

    resposta = cliente.post("/auth/logout")

    assert resposta.status_code == 204
    cookie = _set_cookie(resposta).lower()
    assert cookie.startswith('rfid_sessao="";') or cookie.startswith("rfid_sessao=;")
    assert "max-age=0" in cookie and "path=/" in cookie
    assert cliente.cookies.get("rfid_sessao") is None
    assert consultar(engine, "SELECT motivo_revogacao FROM sessoes")[0][0] == "logout"
    reapresentado = cliente_com_token(token)
    assert reapresentado.get("/auth/me").status_code == 401
    # Logout com o token já revogado e sem sessão: idempotente.
    assert reapresentado.post("/auth/logout").status_code == 204
    assert api_auth().post("/auth/logout").status_code == 204
    assert consultar(engine, "SELECT count(*) FROM sessoes WHERE revogada_em IS NOT NULL")[0][0] == 1


def test_conta_desativada_direto_no_banco_perde_a_sessao(engine, api_auth):
    usuario_id = inserir_usuario(engine, EMAIL)
    cliente = api_auth()
    logar(cliente, EMAIL)

    executar(engine, "UPDATE usuarios SET ativo = false WHERE id = :id", id=usuario_id)

    assert cliente.get("/auth/me").status_code == 401
    assert consultar(engine, "SELECT revogada_em FROM sessoes")[0][0] is None


# --- senha temporária e troca de senha ---------------------------------------


def test_senha_temporaria_so_libera_me_troca_e_logout(engine, api_auth):
    inserir_usuario(engine, EMAIL, perfil="administrador", deve_trocar_senha=True)
    cliente = api_auth()

    login = logar(cliente, EMAIL)
    assert login.status_code == 200
    assert login.json()["usuario"]["deve_trocar_senha"] is True
    assert cliente.get("/auth/me").status_code == 200
    for metodo, rota in (("GET", "/usuarios"), ("GET", "/usuarios/1"),
                         ("POST", "/usuarios/1/desativar")):
        resposta = cliente.request(metodo, rota)
        assert resposta.status_code == 403
        assert resposta.json() == {"detail": "troca_de_senha_obrigatoria"}

    troca = cliente.post("/auth/trocar-senha", json={"senha_atual": SENHA, "nova_senha": NOVA})
    assert troca.status_code == 204
    assert cliente.get("/usuarios").status_code == 200
    assert cliente.get("/auth/me").json()["usuario"]["deve_trocar_senha"] is False


def test_logout_funciona_com_senha_temporaria(engine, api_auth):
    inserir_usuario(engine, EMAIL, deve_trocar_senha=True)
    cliente = api_auth()
    logar(cliente, EMAIL)

    assert cliente.post("/auth/logout").status_code == 204
    assert consultar(engine, "SELECT motivo_revogacao FROM sessoes")[0][0] == "logout"


def test_troca_de_senha_derruba_outras_sessoes_e_mantem_a_atual(engine, api_auth):
    inserir_usuario(engine, EMAIL)
    atual, outra, terceira = api_auth(), api_auth(), api_auth()
    for cliente in (atual, outra, terceira):
        logar(cliente, EMAIL)

    resposta = atual.post("/auth/trocar-senha", json={"senha_atual": SENHA, "nova_senha": NOVA})

    assert resposta.status_code == 204
    assert atual.get("/auth/me").status_code == 200
    assert outra.get("/auth/me").status_code == 401
    assert terceira.get("/auth/me").status_code == 401
    assert sorted(consultar(engine, "SELECT coalesce(motivo_revogacao, '-') FROM sessoes")) == [
        ("-",), ("troca_senha",), ("troca_senha",)]
    assert logar(api_auth(), EMAIL, SENHA).status_code == 401
    assert logar(api_auth(), EMAIL, NOVA).status_code == 200


def test_troca_exige_senha_atual_e_erro_conta_como_falha(engine, api_auth, ajustes_auth):
    ajustes_auth.config = replace(ajustes_auth.config, login_max_tentativas=3)
    usuario_id = inserir_usuario(engine, EMAIL)
    cliente = api_auth()
    logar(cliente, EMAIL)

    for esperado in (1, 2):
        resposta = cliente.post("/auth/trocar-senha",
                                json={"senha_atual": "errada-123", "nova_senha": NOVA})
        assert resposta.status_code == 400
        assert resposta.json() == {"detail": "senha_atual_incorreta"}
        assert consultar(engine, "SELECT tentativas_falhas FROM usuarios WHERE id=:id",
                         id=usuario_id)[0][0] == esperado
    cliente.post("/auth/trocar-senha", json={"senha_atual": "errada-123", "nova_senha": NOVA})

    assert consultar(engine, "SELECT bloqueado_ate FROM usuarios WHERE id=:id",
                     id=usuario_id)[0][0] is not None
    assert logar(api_auth(), EMAIL, SENHA).status_code == 401
    # Bloqueada, nem a senha atual certa troca.
    resposta = cliente.post("/auth/trocar-senha", json={"senha_atual": SENHA, "nova_senha": NOVA})
    assert resposta.status_code == 400
    assert logar(api_auth(), EMAIL, NOVA).status_code == 401


def test_troca_recusa_nova_senha_igual_a_atual(engine, api_auth):
    inserir_usuario(engine, EMAIL, deve_trocar_senha=True)
    cliente = api_auth()
    logar(cliente, EMAIL)

    resposta = cliente.post("/auth/trocar-senha", json={"senha_atual": SENHA, "nova_senha": SENHA})

    assert resposta.status_code == 422
    assert resposta.json() == {"detail": "nova_senha_igual_a_atual"}
    assert SENHA not in resposta.text
    assert cliente.get("/auth/me").json()["usuario"]["deve_trocar_senha"] is True


def test_troca_exige_sessao(api_auth):
    resposta = api_auth().post("/auth/trocar-senha",
                               json={"senha_atual": SENHA, "nova_senha": NOVA})
    assert resposta.status_code == 401


# --- 422 sem eco --------------------------------------------------------------


def test_422_nunca_ecoa_campos_de_senha(engine, admin_logado):
    cliente, _ = admin_logado
    segredo = "Segredo-Unico-42"
    casos = [
        ("post", "/auth/login", {"senha": segredo}),  # e-mail ausente: input = objeto
        ("post", "/auth/login", {"email": EMAIL, "senha": segredo + "x" * 1100}),
        ("post", "/auth/trocar-senha", {"senha_atual": segredo}),
        ("post", "/auth/trocar-senha", {"senha_atual": SENHA, "nova_senha": segredo[:5]}),
        ("post", "/usuarios", {"nome": "X", "email": "x@hupaa.example",
                               "perfil": "operacional", "senha_temporaria": segredo[:5]}),
        ("post", "/usuarios", {"nome": "X", "email": "invalido",
                               "perfil": "operacional", "senha_temporaria": segredo}),
        ("patch", "/usuarios/1", {"senha": segredo}),
        ("post", "/usuarios/1/redefinir-senha", {"senha_temporaria": segredo[:4]}),
        ("post", "/usuarios/1/redefinir-senha", {"nova_senha": segredo}),
    ]
    for metodo, rota, corpo in casos:
        resposta = getattr(cliente, metodo)(rota, json=corpo)
        assert resposta.status_code == 422, (rota, resposta.text)
        assert segredo[:4] not in resposta.text, (rota, resposta.text)


# --- logs ---------------------------------------------------------------------


def test_logs_registram_eventos_esperados_sem_segredos(engine, api_auth, ajustes_auth, caplog):
    caplog.set_level(logging.INFO, logger="api")
    ajustes_auth.config = replace(ajustes_auth.config, login_max_tentativas=2)
    usuario_id = inserir_usuario(engine, EMAIL)
    bloqueado_id = inserir_usuario(engine, "bloqueavel@hupaa.example")
    email_digitado = "senha-digitada-no-email-77"
    senha_errada = "Errada-Unica-55"
    cliente = api_auth()

    logar(cliente, EMAIL)
    token = cliente.cookies.get("rfid_sessao")
    logar(api_auth(), email_digitado, senha_errada)
    for _ in range(2):
        logar(api_auth(), "bloqueavel@hupaa.example", senha_errada)
    cliente.post("/auth/trocar-senha", json={"senha_atual": senha_errada, "nova_senha": NOVA})
    cliente.post("/auth/trocar-senha", json={"senha_atual": SENHA, "nova_senha": NOVA})
    cliente.post("/auth/logout")

    registros = [r for r in caplog.records if r.name.startswith("api")]
    eventos = [json.loads(r.getMessage()) for r in registros]
    nomes = {evento["evento"] for evento in eventos}
    assert {"login_aceito", "login_recusado", "conta_bloqueada", "logout",
            "senha_trocada", "troca_senha_recusada"} <= nomes
    motivos = {e.get("motivo") for e in eventos if e["evento"] == "login_recusado"}
    assert {"conta_inexistente", "senha_incorreta"} <= motivos
    inexistente = [e for e in eventos if e.get("motivo") == "conta_inexistente"]
    assert inexistente and all("usuario_id" not in e for e in inexistente)
    assert {e["usuario_id"] for e in eventos if e["evento"] == "conta_bloqueada"} == {bloqueado_id}
    assert {e["usuario_id"] for e in eventos if e["evento"] == "senha_trocada"} == {usuario_id}

    hashes = [linha[0] for linha in consultar(engine, "SELECT senha_hash FROM usuarios")]
    tokens = [linha[0] for linha in consultar(engine, "SELECT token_hash FROM sessoes")]
    texto = "\n".join(r.getMessage() for r in caplog.records)
    for proibido in (SENHA, NOVA, senha_errada, email_digitado, token, *hashes, *tokens):
        assert proibido not in texto
