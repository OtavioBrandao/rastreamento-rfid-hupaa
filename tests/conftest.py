"""
Fixtures compartilhadas dos testes que precisam de banco (ISS-006, ISS-008, ISS-009,
ISS-010, ISS-011, ISS-012).

Nada de sqlite nem mock: as regras testadas aqui (UNIQUE de
`nome_normalizado`, `server_default now()`, TRUNCATE ... CASCADE) só
existem de verdade no Postgres. Testar contra outro banco validaria um
comportamento que não é o de produção.

Banco usado: `TEST_DATABASE_URL`, e SÓ ela. Não existe fallback para
`DATABASE_URL` de propósito: a fixture `truncate_all` roda TRUNCATE de
verdade, e `DATABASE_URL` é a variável que fica exportada no shell por
outros motivos (testar a API na mão, rodar o alembic contra o Neon). Um
fallback silencioso transformaria "esqueci uma variável exportada em
outro terminal" em "apaguei a tabela do ambiente errado".

Sem `TEST_DATABASE_URL`, estes testes são PULADOS — os testes antigos do
repositório (ingestão MQTT, parsing) não precisam de banco e continuam
rodando normalmente. Se a variável existe mas o banco não responde, o
erro sobe: "configurado e quebrado" não pode passar por "não configurado".

Segunda trava, estrutural: a URL precisa apontar para host local
(localhost/127.0.0.1/::1 ou socket Unix). Nenhum ambiente gerenciado —
Neon incluído — resolve para localhost, então isso descarta a classe
inteira de "apontei a suíte para um banco remoto". A alternativa de
checar se o nome do banco contém "test" seria frágil nos dois sentidos:
`rfid_hospital_dev` não bateria, e nada impede um banco sério chamado
`rfid_test`.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

# Fixtures da ISS-026 (autenticação), definidas em `tests/suporte_auth.py` e
# registradas aqui para qualquer módulo de teste poder pedi-las pelo nome.
from suporte_auth import (  # noqa: F401 - fixtures
    admin_logado,
    ajustes_auth,
    api_auth,
    relogio,
)

from alembic import command
from db.models import Andar, Antena, Leitor, Setor, Zona

# Só estas: o TRUNCATE ... CASCADE limparia meio schema junto se a lista
# crescesse sem necessidade. Começou em ("equipamentos", "tipos_equipamento")
# (ISS-009/ISS-008), ganhou tags/associacoes/auditorias (ISS-010) e a
# hierarquia física + o que referencia zonas (ISS-011) — mesmo critério: só
# o que os testes escrevem. TRUNCATE com várias tabelas na mesma instrução
# resolve a ordem de dependência sozinho (não precisa listar filhos antes de
# pais); o CASCADE leva junto o que depender delas (passagens, leituras...).
TABELAS_DO_CRUD = (
    "mapeamentos_antena_portal",
    "auditorias",
    # ISS-026. `perfis` fica de fora de propósito: quem semeia é a migration,
    # e truncá-la deixaria a API sem perfil para atribuir.
    "sessoes",
    "usuarios",
    "associacoes_tag_equipamento",
    "historico_movimentacoes",
    "equipamentos",
    "tipos_equipamento",
    "tags",
    "antenas",
    "leitores",
    "portais",
    "zonas",
    "setores",
    "andares",
)


HOSTS_LOCAIS = {"localhost", "127.0.0.1", "::1"}

MARCADOR_AUTENTICACAO_REAL = "autenticacao_real"


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        f"{MARCADOR_AUTENTICACAO_REAL}: não substitui a sessão por um administrador de "
        "teste; o teste faz login de verdade (ISS-026/ISS-027).",
    )


@pytest.fixture(autouse=True)
def administrador_de_teste(request):
    """
    ISS-027: toda rota de negócio passou a exigir sessão e permissão. Os testes
    de CRUD anteriores chamam a API sem login; para eles, `sessao_autenticada`
    é substituída por um ADMINISTRADOR TRANSIENTE — objeto em memória, sem
    linha em `usuarios` nem em `sessoes`. A autorização continua rodando de
    verdade por cima dele (matriz, senha temporária, log).

    Opt-out: `@pytest.mark.autenticacao_real` (ou `pytestmark`) nos módulos que
    testam login, sessão e permissão com cookie real.

    ATENÇÃO ISS-028: quando os serviços passarem a gravar o AUTOR (ex.:
    `auditorias.usuario_id`), este admin sem linha no banco violaria a FK —
    será preciso inserir um usuário real aqui e apontar a sessão para ele.
    """
    if request.node.get_closest_marker(MARCADOR_AUTENTICACAO_REAL):
        yield
        return
    from api.dependencias_auth import sessao_autenticada
    from api.main import app
    from api.service_auth import PERFIL_ADMINISTRADOR, SessaoAutenticada
    from db.models import Perfil, Usuario

    admin = Usuario(
        id=0, nome="Administrador de teste", email="admin-teste@hupaa.example",
        perfil=Perfil(id=0, nome=PERFIL_ADMINISTRADOR), ativo=True, deve_trocar_senha=False,
    )
    sessao = SessaoAutenticada(
        sessao_id=0, expira_em=datetime(2999, 1, 1, tzinfo=timezone.utc), usuario=admin
    )
    app.dependency_overrides[sessao_autenticada] = lambda: sessao
    try:
        yield
    finally:
        app.dependency_overrides.pop(sessao_autenticada, None)


def _url_do_banco_de_teste() -> str | None:
    return os.environ.get("TEST_DATABASE_URL")


def _exigir_host_local(url: str) -> None:
    """Aborta se a URL não for de um banco local. Ver docstring do módulo."""
    host = make_url(url).host
    # host vazio/None = socket Unix, que por definição é local.
    if host and host not in HOSTS_LOCAIS:
        raise RuntimeError(
            f"TEST_DATABASE_URL aponta para o host {host!r}, que não é local. "
            "A suíte roda TRUNCATE nas tabelas do CRUD — ela só pode apontar "
            f"para um banco descartável em {sorted(HOSTS_LOCAIS)}."
        )


@pytest.fixture(scope="session")
def engine():
    url = _url_do_banco_de_teste()
    if not url:
        pytest.skip(
            "Testes de banco exigem TEST_DATABASE_URL apontando para um Postgres "
            "local descartável com as migrations aplicadas. Sem fallback para "
            "DATABASE_URL: a suíte trunca tabelas."
        )

    _exigir_host_local(url)

    engine = create_engine(url, future=True)
    # Falha alto e cedo: sem isso, cada teste morreria com um OperationalError
    # diferente e ninguém entenderia que o problema é só o banco fora do ar.
    with engine.connect() as conexao:
        conexao.execute(text("SELECT 1"))
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db(engine):
    """
    Sessão isolada por teste, revertida no final.

    O SAVEPOINT é necessário porque a camada de serviço chama
    `session.commit()` e `session.rollback()` de verdade — é justamente o
    comportamento sob teste. Ligada direto ao engine, essa sessão gravaria
    definitivo e um teste veria o dado do outro.

    `join_transaction_mode="create_savepoint"` é o que faz a sessão nascer
    dentro da transação externa e traduzir cada commit/rollback dela em
    liberar/voltar um SAVEPOINT, reabrindo outro em seguida. A receita
    antiga (listener manual em "after_transaction_end") cobre o commit,
    mas NÃO o rollback: o `session.rollback()` que o serviço faz ao pegar
    IntegrityError derruba a transação externa junto ("transaction already
    deassociated from connection"), e a partir dali os commits do teste
    passam a ser definitivos e vazam para o teste seguinte. Verificado
    neste banco, não deduzido.
    """
    conexao = engine.connect()
    transacao_externa = conexao.begin()
    try:
        # Estado inicial conhecido DENTRO da transação externa: o banco de
        # desenvolvimento tem os tipos do seed (e pode ter sobras de smoke
        # test manual — tags, associações, auditorias, hierarquia física), e um teste de
        # paginação que conta linhas não pode depender de quem rodou o quê
        # antes. Como está dentro da transação externa, o rollback do final
        # devolve tudo — isto só ESCONDE o dado pré-existente pela duração
        # deste teste, não apaga de verdade.
        # Ordem por FK: filhos antes dos pais. mapeamentos_antena_portal
        # referencia antenas, portais e zonas; associacoes_tag_equipamento e
        # historico_movimentacoes referenciam equipamentos; equipamentos
        # referencia tipos_equipamento, zonas e passagens; passagens referencia
        # portais/antenas/leituras_brutas; antenas -> leitores -> portais;
        # portais/antenas/historico referenciam zonas; zonas -> setores ->
        # andares. auditorias e sessoes referenciam usuarios (ISS-026), então
        # vêm antes dele; `perfis` não é limpa (semeada pela migration).
        # ISS-028: `auditorias` é append-only (trigger recusa DELETE); TRUNCATE
        # não dispara trigger de linha e, aqui dentro da transação externa,
        # também é desfeito pelo rollback do final.
        conexao.execute(text("TRUNCATE TABLE auditorias"))
        for tabela in (
            "mapeamentos_antena_portal",
            "sessoes",
            "usuarios",
            "associacoes_tag_equipamento",
            "historico_movimentacoes",
            "equipamentos",
            "passagens",
            "leituras_brutas",
            "antenas",
            "leitores",
            "portais",
            "zonas",
            "setores",
            "andares",
            "tipos_equipamento",
            "tags",
        ):
            conexao.execute(text(f"DELETE FROM {tabela}"))

        session = Session(bind=conexao, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
    finally:
        # Protect connection pool against leaks if setup DELETEs or session creation fail.
        if transacao_externa.is_active:
            transacao_externa.rollback()
        conexao.close()


@pytest.fixture
def truncate_all(engine):
    """
    Limpeza real (commitada) das tabelas do CRUD.

    Usada pelos testes que sobem a API: o TestClient abre a PRÓPRIA
    sessão/conexão e por isso não enxerga nada do que a fixture `db`
    escreveu dentro da transação externa dela. Para esses testes o dado
    precisa estar commitado de verdade — e então precisa ser limpo de
    verdade, antes e depois.
    """

    def limpar() -> None:
        with engine.begin() as conexao:
            conexao.execute(
                text(
                    "TRUNCATE TABLE "
                    + ", ".join(TABELAS_DO_CRUD)
                    + " RESTART IDENTITY CASCADE"
                )
            )

    limpar()
    yield
    limpar()


# Fixtures isoladas da ISS-006 para testes de persistência e migrations
@pytest.fixture
def pg_empty_schema(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("exige TEST_DATABASE_URL de PostgreSQL descartável")
    _exigir_host_local(url)
    engine = create_engine(url, hide_parameters=True)
    schema = "iss006_" + uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    isolated_url = engine.url.update_query_dict({"options": "-csearch_path=" + schema})
    isolated = create_engine(isolated_url, hide_parameters=True)
    monkeypatch.setenv("DATABASE_URL", isolated_url.render_as_string(hide_password=False))
    try:
        yield isolated
    finally:
        isolated.dispose()
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def migration_config():
    config = Config()
    config.set_main_option("script_location", "alembic")
    return config


@pytest.fixture
def pg_engine(pg_empty_schema):
    command.upgrade(migration_config(), "head")
    return pg_empty_schema


@pytest.fixture
def topology(pg_engine):
    with pg_engine.begin() as connection:
        floor = connection.execute(
            Andar.__table__.insert().values(nome="teste", nome_normalizado="teste").returning(Andar.id)
        ).scalar_one()
        sector = connection.execute(
            Setor.__table__.insert().values(andar_id=floor, nome="teste", nome_normalizado="teste").returning(Setor.id)
        ).scalar_one()
        zone = connection.execute(
            Zona.__table__.insert().values(setor_id=sector, nome="teste", nome_normalizado="teste").returning(Zona.id)
        ).scalar_one()
        reader = connection.execute(
            Leitor.__table__.insert().values(
                reader_id="reader-01",
                identificador_serial="serial-independente",
                fabricante="teste",
                modelo="teste",
            ).returning(Leitor.id)
        ).scalar_one()
        antenna = connection.execute(
            Antena.__table__.insert().values(
                leitor_id=reader,
                porta_numero=1,
                zona_associada_id=zone,
                funcao="indefinido",
            ).returning(Antena.id)
        ).scalar_one()
    return {"reader": reader, "antenna": antenna, "zone": zone}
