"""Contrato HTTP da administração de usuários (ISS-026)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session
from suporte_auth import (
    SENHA,
    consultar,
    executar,
    inserir_usuario,
    logar,
)

from api import service_usuarios

# ISS-027: login e cookie reais; sem o administrador de teste do conftest.
pytestmark = pytest.mark.autenticacao_real

TEMP = "temporaria-123"
CAMPOS_RESPOSTA = {
    "id", "nome", "email", "perfil", "ativo", "deve_trocar_senha", "bloqueado_ate",
    "ultimo_login_em", "created_at", "updated_at",
}


def _criar(cliente, email="joao@hupaa.example", perfil="operacional", nome="João"):
    return cliente.post("/usuarios", json={
        "nome": nome, "email": email, "perfil": perfil, "senha_temporaria": TEMP,
    })


def _auditorias(engine, entidade_id: int):
    return consultar(
        engine,
        "SELECT usuario_id, acao, dados_antes, dados_depois FROM auditorias "
        "WHERE entidade = 'usuarios' AND entidade_id = :id "
        # ISS-028: eventos de sessão do alvo também entram na trilha; aqui só cadastro.
        "AND acao NOT IN ('login_aceito', 'login_recusado', 'logout', 'conta_bloqueada') "
        "ORDER BY id",
        id=entidade_id,
    )


def _sem_segredo(valor) -> None:
    texto = str(valor)
    assert "senha_hash" not in texto and "$argon2" not in texto
    assert TEMP not in texto and SENHA not in texto


# --- acesso -------------------------------------------------------------------

ROTAS = [
    ("GET", "/usuarios", None),
    ("POST", "/usuarios", {"nome": "X", "email": "x@hupaa.example", "perfil": "operacional",
                           "senha_temporaria": TEMP}),
    ("GET", "/usuarios/1", None),
    ("PATCH", "/usuarios/1", {"nome": "Y"}),
    ("POST", "/usuarios/1/desativar", None),
    ("POST", "/usuarios/1/reativar", None),
    ("POST", "/usuarios/1/redefinir-senha", {"senha_temporaria": TEMP}),
]


@pytest.mark.parametrize(("metodo", "rota", "corpo"), ROTAS)
def test_todas_as_rotas_exigem_sessao(api_auth, metodo, rota, corpo):
    resposta = api_auth().request(metodo, rota, json=corpo)
    assert resposta.status_code == 401


@pytest.mark.parametrize(("metodo", "rota", "corpo"), ROTAS)
def test_todas_as_rotas_exigem_administrador(engine, api_auth, metodo, rota, corpo):
    inserir_usuario(engine, "op@hupaa.example")
    cliente = api_auth()
    logar(cliente, "op@hupaa.example")

    resposta = cliente.request(metodo, rota, json=corpo)

    assert resposta.status_code == 403
    assert resposta.json() == {"detail": "acesso_negado"}


def test_admin_rebaixado_perde_acesso_na_sessao_aberta(engine, admin_logado):
    cliente, admin_id = admin_logado
    inserir_usuario(engine, "outro-admin@hupaa.example", perfil="administrador")
    executar(engine, "UPDATE usuarios SET perfil_id = (SELECT id FROM perfis "
             "WHERE nome='operacional') WHERE id = :id", id=admin_id)

    assert cliente.get("/usuarios").status_code == 403


# --- criar --------------------------------------------------------------------


def test_criar_normaliza_email_exige_troca_e_audita(engine, admin_logado):
    cliente, admin_id = admin_logado

    resposta = _criar(cliente, email="  Joao@HUPAA.example ")

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert set(corpo) == CAMPOS_RESPOSTA
    assert corpo["email"] == "joao@hupaa.example"
    assert corpo["deve_trocar_senha"] is True
    assert corpo["perfil"] == "operacional" and corpo["ativo"] is True
    (autor, acao, antes, depois), = _auditorias(engine, corpo["id"])
    assert (autor, acao, antes) == (admin_id, "criar", None)
    assert (depois["email"], depois["perfil"], depois["deve_trocar_senha"]) == (
        "joao@hupaa.example", "operacional", True)
    _sem_segredo(depois)
    (hash_salvo,) = consultar(engine, "SELECT senha_hash FROM usuarios WHERE id=:id",
                              id=corpo["id"])[0]
    assert hash_salvo.startswith("$argon2id$") and TEMP not in hash_salvo


def test_criar_email_duplicado_mesmo_com_caixa_diferente_409(engine, admin_logado):
    cliente, _ = admin_logado
    assert _criar(cliente).status_code == 201

    resposta = _criar(cliente, email="JOAO@hupaa.example")

    assert resposta.status_code == 409
    assert consultar(engine, "SELECT count(*) FROM usuarios")[0][0] == 2


@pytest.mark.parametrize("email", ["sem-arroba", "a@b", "joão@hupaa.example", " @x.org"])
def test_criar_recusa_email_invalido(admin_logado, email):
    cliente, _ = admin_logado
    assert _criar(cliente, email=email).status_code == 422


def test_usuario_criado_entra_com_senha_temporaria_e_fica_restrito(engine, admin_logado,
                                                                   api_auth):
    cliente, _ = admin_logado
    _criar(cliente, perfil="administrador")
    novo = api_auth()

    assert logar(novo, "joao@hupaa.example", TEMP).status_code == 200
    assert novo.get("/usuarios").json() == {"detail": "troca_de_senha_obrigatoria"}


# --- listar e consultar -------------------------------------------------------


def test_listar_paginado_com_filtros(engine, admin_logado):
    cliente, admin_id = admin_logado
    ids = [inserir_usuario(engine, f"u{i}@hupaa.example") for i in range(4)]
    executar(engine, "UPDATE usuarios SET ativo = false WHERE id = :id", id=ids[0])

    pagina = cliente.get("/usuarios", params={"page": 2, "size": 2}).json()
    assert set(pagina) == {"items", "page", "size", "total", "pages"}
    assert (pagina["page"], pagina["size"], pagina["total"], pagina["pages"]) == (2, 2, 5, 3)
    assert [item["id"] for item in pagina["items"]] == ids[1:3]
    assert all(set(item) == CAMPOS_RESPOSTA for item in pagina["items"])

    admins = cliente.get("/usuarios", params={"perfil": "administrador"}).json()
    assert [item["id"] for item in admins["items"]] == [admin_id]
    inativos = cliente.get("/usuarios", params={"ativo": "false"}).json()
    assert [item["id"] for item in inativos["items"]] == [ids[0]]
    combinados = cliente.get("/usuarios", params={"ativo": "true", "perfil": "operacional"})
    assert combinados.json()["total"] == 3
    assert cliente.get("/usuarios", params={"perfil": "root"}).status_code == 422
    assert cliente.get("/usuarios", params={"size": 101}).status_code == 422


def test_consultar_e_404(engine, admin_logado):
    cliente, admin_id = admin_logado

    assert cliente.get(f"/usuarios/{admin_id}").json()["email"] == "admin@hupaa.example"
    assert cliente.get("/usuarios/999999").status_code == 404


# --- editar -------------------------------------------------------------------


def test_patch_edita_nome_e_perfil_e_audita(engine, admin_logado):
    cliente, admin_id = admin_logado
    alvo = inserir_usuario(engine, "alvo@hupaa.example", nome="Antigo")

    resposta = cliente.patch(f"/usuarios/{alvo}", json={"nome": " Novo ", "perfil": "administrador"})

    assert resposta.status_code == 200
    assert (resposta.json()["nome"], resposta.json()["perfil"]) == ("Novo", "administrador")
    (autor, acao, antes, depois), = _auditorias(engine, alvo)
    assert (autor, acao) == (admin_id, "atualizar")
    assert (antes["nome"], antes["perfil"]) == ("Antigo", "operacional")
    assert (depois["nome"], depois["perfil"]) == ("Novo", "administrador")
    _sem_segredo([antes, depois])


@pytest.mark.parametrize("corpo", [
    {"email": "novo@hupaa.example"},
    {"nome": "X", "email": "novo@hupaa.example"},
    {"ativo": False},
    {"nome": None},
    {"perfil": None},
    {"perfil": "root"},
    {"nome": "   "},
])
def test_patch_rejeita_email_campos_extras_e_nulos(engine, admin_logado, corpo):
    cliente, _ = admin_logado
    alvo = inserir_usuario(engine, "alvo@hupaa.example")

    assert cliente.patch(f"/usuarios/{alvo}", json=corpo).status_code == 422
    assert consultar(engine, "SELECT email FROM usuarios WHERE id=:id", id=alvo)[0][0] == (
        "alvo@hupaa.example")


def test_rebaixar_o_ultimo_admin_ativo_409(engine, admin_logado):
    cliente, admin_id = admin_logado
    inserir_usuario(engine, "admin-inativo@hupaa.example", perfil="administrador", ativo=False)

    resposta = cliente.patch(f"/usuarios/{admin_id}", json={"perfil": "operacional"})

    assert resposta.status_code == 409
    assert cliente.get(f"/usuarios/{admin_id}").json()["perfil"] == "administrador"
    assert _auditorias(engine, admin_id) == []


def test_rebaixar_admin_quando_ha_outro_ativo(engine, admin_logado):
    cliente, admin_id = admin_logado
    outro = inserir_usuario(engine, "admin2@hupaa.example", perfil="administrador")

    assert cliente.patch(f"/usuarios/{outro}", json={"perfil": "operacional"}).status_code == 200
    assert cliente.patch(f"/usuarios/{admin_id}", json={"perfil": "operacional"}).status_code == 409


# --- desativar ----------------------------------------------------------------


def test_desativar_derruba_sessao_aberta_e_impede_login(engine, admin_logado, api_auth):
    cliente, admin_id = admin_logado
    alvo = inserir_usuario(engine, "alvo@hupaa.example")
    sessao_alvo = api_auth()
    logar(sessao_alvo, "alvo@hupaa.example")

    resposta = cliente.post(f"/usuarios/{alvo}/desativar")

    assert resposta.status_code == 200 and resposta.json()["ativo"] is False
    assert sessao_alvo.get("/auth/me").status_code == 401
    assert consultar(engine, "SELECT motivo_revogacao FROM sessoes WHERE usuario_id=:id",
                     id=alvo) == [("desativacao",)]
    assert logar(api_auth(), "alvo@hupaa.example").status_code == 401
    (_, acao, antes, depois), = _auditorias(engine, alvo)
    assert (acao, antes, depois) == ("inativar", {"ativo": True}, {"ativo": False})


def test_admin_nao_desativa_nem_redefine_a_propria_conta(engine, admin_logado):
    cliente, admin_id = admin_logado
    inserir_usuario(engine, "admin2@hupaa.example", perfil="administrador")

    assert cliente.post(f"/usuarios/{admin_id}/desativar").status_code == 409
    resposta = cliente.post(f"/usuarios/{admin_id}/redefinir-senha",
                            json={"senha_temporaria": TEMP})
    assert resposta.status_code == 409
    assert cliente.get("/auth/me").status_code == 200
    assert logar(cliente, "admin@hupaa.example").status_code == 200


def test_desativar_outro_admin_mantem_um_ativo(engine, admin_logado):
    cliente, admin_id = admin_logado
    outro = inserir_usuario(engine, "admin2@hupaa.example", perfil="administrador")

    assert cliente.post(f"/usuarios/{outro}/desativar").status_code == 200
    assert cliente.patch(f"/usuarios/{admin_id}", json={"perfil": "operacional"}).status_code == 409


def test_404_nas_operacoes(admin_logado):
    cliente, _ = admin_logado
    for rota in ("desativar", "reativar"):
        assert cliente.post(f"/usuarios/999999/{rota}").status_code == 404
    assert cliente.patch("/usuarios/999999", json={"nome": "X"}).status_code == 404
    assert cliente.post("/usuarios/999999/redefinir-senha",
                        json={"senha_temporaria": TEMP}).status_code == 404


# --- reativar -----------------------------------------------------------------


def test_reativar_zera_bloqueio_e_nao_ressuscita_sessao(engine, admin_logado, api_auth):
    cliente, _ = admin_logado
    alvo = inserir_usuario(engine, "alvo@hupaa.example")
    antiga = api_auth()
    logar(antiga, "alvo@hupaa.example")
    cliente.post(f"/usuarios/{alvo}/desativar")
    executar(engine, "UPDATE usuarios SET bloqueado_ate = now() + interval '1 day', "
             "tentativas_falhas = 3 WHERE id = :id", id=alvo)

    resposta = cliente.post(f"/usuarios/{alvo}/reativar")

    assert resposta.status_code == 200
    assert (resposta.json()["ativo"], resposta.json()["bloqueado_ate"]) == (True, None)
    assert consultar(engine, "SELECT tentativas_falhas FROM usuarios WHERE id=:id",
                     id=alvo)[0][0] == 0
    assert antiga.get("/auth/me").status_code == 401
    assert logar(api_auth(), "alvo@hupaa.example").status_code == 200
    assert _auditorias(engine, alvo)[-1][1] == "reativar"


def test_reativar_apos_desativacao_direta_no_banco_nao_ressuscita(engine, admin_logado,
                                                                   api_auth):
    cliente, _ = admin_logado
    alvo = inserir_usuario(engine, "alvo@hupaa.example")
    antiga = api_auth()
    logar(antiga, "alvo@hupaa.example")
    executar(engine, "UPDATE usuarios SET ativo = false WHERE id = :id", id=alvo)

    assert cliente.post(f"/usuarios/{alvo}/reativar").status_code == 200

    assert antiga.get("/auth/me").status_code == 401
    assert consultar(engine, "SELECT motivo_revogacao FROM sessoes WHERE usuario_id=:id",
                     id=alvo) == [("desativacao",)]


def test_reativar_conta_ativa_so_desbloqueia_sem_derrubar_sessao(engine, admin_logado, api_auth):
    cliente, _ = admin_logado
    alvo = inserir_usuario(engine, "alvo@hupaa.example")
    aberta = api_auth()
    logar(aberta, "alvo@hupaa.example")
    executar(engine, "UPDATE usuarios SET bloqueado_ate = now() + interval '1 day' "
             "WHERE id = :id", id=alvo)

    assert cliente.post(f"/usuarios/{alvo}/reativar").status_code == 200

    assert aberta.get("/auth/me").status_code == 200
    assert logar(api_auth(), "alvo@hupaa.example").status_code == 200


# --- redefinir senha ----------------------------------------------------------


def test_redefinir_senha_revoga_sessoes_e_exige_troca(engine, admin_logado, api_auth):
    cliente, admin_id = admin_logado
    alvo = inserir_usuario(engine, "alvo@hupaa.example")
    antiga = api_auth()
    logar(antiga, "alvo@hupaa.example")
    executar(engine, "UPDATE usuarios SET bloqueado_ate = now() + interval '1 day' "
             "WHERE id = :id", id=alvo)

    resposta = cliente.post(f"/usuarios/{alvo}/redefinir-senha", json={"senha_temporaria": TEMP})

    assert resposta.status_code == 200
    assert resposta.json()["deve_trocar_senha"] is True
    assert antiga.get("/auth/me").status_code == 401
    assert consultar(engine, "SELECT motivo_revogacao FROM sessoes WHERE usuario_id=:id",
                     id=alvo) == [("redefinicao_senha",)]
    assert logar(api_auth(), "alvo@hupaa.example", SENHA).status_code == 401
    nova = api_auth()
    assert logar(nova, "alvo@hupaa.example", TEMP).status_code == 200
    assert nova.get("/usuarios").status_code == 403
    (autor, acao, _antes, depois), = _auditorias(engine, alvo)
    assert (autor, acao, depois["senha"]) == (admin_id, "alterar_senha", "alterada")
    assert depois["deve_trocar_senha"] is True
    _sem_segredo(_auditorias(engine, alvo))


# --- respostas sem segredo ----------------------------------------------------


def test_nenhuma_resposta_expoe_senha_hash_ou_token(engine, admin_logado):
    cliente, admin_id = admin_logado
    token = cliente.cookies.get("rfid_sessao")
    criado = _criar(cliente).json()
    respostas = [
        cliente.get("/auth/me"),
        cliente.get("/usuarios"),
        cliente.get(f"/usuarios/{criado['id']}"),
        cliente.patch(f"/usuarios/{criado['id']}", json={"nome": "Outro"}),
        cliente.post(f"/usuarios/{criado['id']}/redefinir-senha", json={"senha_temporaria": TEMP}),
        cliente.post(f"/usuarios/{criado['id']}/desativar"),
        cliente.post(f"/usuarios/{criado['id']}/reativar"),
    ]
    hashes = [linha[0] for linha in consultar(engine, "SELECT senha_hash FROM usuarios")]
    for resposta in respostas:
        assert resposta.status_code == 200, resposta.text
        for proibido in (TEMP, SENHA, token, "senha_hash", "$argon2", *hashes):
            assert proibido not in resposta.text


# --- serviço: autor que perdeu o perfil sob lock ------------------------------


def test_autor_sem_perfil_de_admin_e_recusado_sob_lock(engine, api_auth):
    admin = inserir_usuario(engine, "admin@hupaa.example", perfil="administrador")
    operacional = inserir_usuario(engine, "op@hupaa.example")

    with Session(bind=engine) as db:
        with pytest.raises(service_usuarios.AutorSemPermissao, match="^acesso_negado$"):
            service_usuarios.atualizar(db, operacional, admin, perfil="operacional")

    assert consultar(engine, "SELECT count(*) FROM auditorias")[0][0] == 0


def test_autor_rebaixado_durante_a_request_recebe_a_negacao_unica(engine, admin_logado,
                                                                  monkeypatch):
    """A corrida (autor perde o perfil enquanto espera o lock) responde como qualquer negação."""
    cliente, _ = admin_logado
    alvo = inserir_usuario(engine, "alvo@hupaa.example")

    def perdeu_o_perfil(*_args, **_kwargs):
        raise service_usuarios.AutorSemPermissao()

    monkeypatch.setattr(service_usuarios, "atualizar", perdeu_o_perfil)
    resposta = cliente.patch(f"/usuarios/{alvo}", json={"nome": "Outro"})

    assert (resposta.status_code, resposta.json()) == (403, {"detail": "acesso_negado"})
