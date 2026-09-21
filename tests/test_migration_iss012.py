"""
Testes das migrations da ISS-012 com DADOS PRÉ-EXISTENTES (não confiam em banco vazio).

São DUAS revisões: `019782a38ff7` (portal_id na antena, reader_id...) e
`6b3e5f7a91c4` (índice único parcial da porta + timestamps). Os testes da
primeira miram a REVISÃO dela explicitamente (não "head"), para continuarem
testando o que dizem testar quando a cadeia crescer.

A primeira migration troca `leitores.portal_id` por `antenas.portal_id`. O risco que
este arquivo cobre: a informação de "em que portal o leitor está instalado"
sumir em silêncio em instalações que já têm dado. Por isso cada cenário parte do
esquema ANTIGO (revisão anterior), insere linhas, migra e confere.

Cada teste roda num banco DESCARTÁVEL próprio (CREATE DATABASE ... / DROP ...),
nunca no banco das outras suítes: `downgrade` derruba colunas de que os demais
testes dependem, e um downgrade num banco compartilhado quebraria a suíte.

`alembic` roda por SUBPROCESSO, não em-processo: o `env.py` chama `fileConfig`,
que reconfigura o logging do processo (e poderia desabilitar os loggers que
outros testes, como os de ingestão, inspecionam).

Herda a trava da fixture `engine` (exige TEST_DATABASE_URL e recusa host que não
seja local). Precisa de permissão de CREATEDB — o usuário do compose/CI é o dono
do cluster.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

RAIZ = Path(__file__).resolve().parent.parent
REVISAO_ANTERIOR = "af6d99290414"  # ISS-011
REVISAO_ISS012 = "019782a38ff7"  # portal_id na antena, reader_id, ativo, parametros_ingestao
REVISAO_ISS012_AJUSTES = "6b3e5f7a91c4"  # índice único parcial da porta + timestamps (head)


@pytest.fixture
def banco(engine):
    """URL de um banco novo e vazio, removido no final."""
    nome = f"rfid_mig_{uuid.uuid4().hex[:10]}"
    admin = create_engine(engine.url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conexao:
        conexao.execute(text(f'CREATE DATABASE "{nome}"'))
    try:
        yield engine.url.set(database=nome)
    finally:
        with admin.connect() as conexao:
            conexao.execute(text(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)'))
        admin.dispose()


def _alembic(url, *argumentos: str) -> subprocess.CompletedProcess:
    ambiente = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *argumentos],
        cwd=RAIZ,
        env=ambiente,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _saida(processo: subprocess.CompletedProcess) -> str:
    return processo.stdout + processo.stderr


def _migrar(url, alvo: str) -> None:
    processo = _alembic(url, "upgrade" if alvo != "base" else "downgrade", alvo)
    assert processo.returncode == 0, _saida(processo)


def _sql(url, instrucoes: str, **parametros):
    motor = create_engine(url)
    try:
        with motor.begin() as conexao:
            resultado = conexao.execute(text(instrucoes), parametros)
            return resultado.fetchall() if resultado.returns_rows else None
    finally:
        motor.dispose()


def _semear_esquema_antigo(url) -> None:
    """
    Instalação "antiga" (revisão da ISS-011, com `leitores.portal_id`):
      leitor 1 -> portal 1, com 2 antenas          (deve replicar para AS DUAS)
      leitor 2 -> portal 2, com 1 antena
      leitor 3 -> sem portal, com 1 antena         (antena fica sem portal)
      leitor 4 -> sem portal e sem antena
    """
    _migrar(url, REVISAO_ANTERIOR)
    _sql(
        url,
        """
        INSERT INTO andares (nome, nome_normalizado) VALUES ('4o', '4o');
        INSERT INTO setores (andar_id, nome, nome_normalizado) VALUES (1, 'Ala', 'ala');
        INSERT INTO zonas (setor_id, nome, nome_normalizado)
            VALUES (1,'Z1','z1'), (1,'Z2','z2'), (1,'Z3','z3'), (1,'Z4','z4');
        INSERT INTO portais (nome, zona_a_id, zona_b_id) VALUES ('P1', 1, 2), ('P2', 3, 4);
        INSERT INTO leitores (portal_id, fabricante, modelo, identificador_serial) VALUES
            (1, 'Identix', 'EZ700', 'SN-L1'),
            (2, 'Identix', 'EZ700', 'SN-L2'),
            (NULL, 'Identix', 'EZ700', 'SN-L3'),
            (NULL, 'Identix', 'EZ700', 'SN-L4');
        INSERT INTO antenas (leitor_id, porta_numero, zona_associada_id, funcao) VALUES
            (1, 1, 1, 'entrada'), (1, 2, 2, 'saida'), (2, 1, 3, 'entrada'), (3, 1, 4, 'indefinido');
        """,
    )


def _portais_das_antenas(url) -> dict[int, int | None]:
    return dict(_sql(url, "SELECT id, portal_id FROM antenas ORDER BY id"))


def _portais_dos_leitores(url) -> dict[int, int | None]:
    return dict(_sql(url, "SELECT id, portal_id FROM leitores ORDER BY id"))


def _colunas(url, tabela: str) -> set[str]:
    linhas = _sql(url, "SELECT column_name FROM information_schema.columns WHERE table_name = :t", t=tabela)
    return {linha[0] for linha in linhas}


def _revisao_atual(url) -> str:
    return _sql(url, "SELECT version_num FROM alembic_version")[0][0]


# --- upgrade ---------------------------------------------------------------------------------


def test_upgrade_replica_o_portal_do_leitor_para_todas_as_antenas_e_preenche_reader_id(banco):
    _semear_esquema_antigo(banco)

    _migrar(banco, REVISAO_ISS012)

    # o portal do leitor foi replicado para TODAS as antenas dele; quem não tinha fica sem
    assert _portais_das_antenas(banco) == {1: 1, 2: 1, 3: 2, 4: None}
    # a coluna antiga caiu, as novas existem
    assert "portal_id" not in _colunas(banco, "leitores")
    assert {"reader_id", "ativo", "parametros_ingestao"} <= _colunas(banco, "leitores")
    assert {"portal_id", "ativo"} <= _colunas(banco, "antenas")
    assert "ativo" in _colunas(banco, "portais")
    # reader_id nasce igual ao serial (ponto de partida) e independente daí em diante
    assert _sql(banco, "SELECT reader_id, identificador_serial FROM leitores ORDER BY id") == [
        ("SN-L1", "SN-L1"),
        ("SN-L2", "SN-L2"),
        ("SN-L3", "SN-L3"),
        ("SN-L4", "SN-L4"),
    ]
    # tudo cadastrado antes continua ATIVO; parametros_ingestao é SQL NULL
    assert _sql(banco, "SELECT bool_and(ativo) FROM leitores")[0][0] is True
    assert _sql(banco, "SELECT bool_and(ativo) FROM antenas")[0][0] is True
    assert _sql(banco, "SELECT bool_and(ativo) FROM portais")[0][0] is True
    assert _sql(banco, "SELECT count(*) FROM leitores WHERE parametros_ingestao IS NULL")[0][0] == 4


def test_upgrade_cria_as_constraints_nomeadas(banco):
    _migrar(banco, REVISAO_ISS012)

    constraints = {linha[0] for linha in _sql(banco, "SELECT conname FROM pg_constraint")}
    indices = {linha[0] for linha in _sql(banco, "SELECT indexname FROM pg_indexes")}
    assert {"uq_leitores_reader_id", "fk_antenas_portal_id", "uq_antena_por_porta_leitor"} <= constraints
    assert "ix_antenas_portal_id" in indices
    # reader_id é NOT NULL
    assert _sql(
        banco,
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name='leitores' AND column_name='reader_id'",
    )[0][0] == "NO"


def test_upgrade_aborta_se_um_leitor_com_portal_nao_tem_nenhuma_antena(banco):
    """Sem antena não há linha para carregar o portal: perderia em silêncio — então aborta."""
    _semear_esquema_antigo(banco)
    _sql(banco, "UPDATE leitores SET portal_id = 2 WHERE identificador_serial = 'SN-L4'")

    processo = _alembic(banco, "upgrade", REVISAO_ISS012)

    assert processo.returncode != 0
    saida = _saida(processo)
    assert "SEM nenhuma antena" in saida and "SN-L4" in saida
    # DDL transacional: o esquema antigo ficou intacto e a revisão não avançou
    assert _revisao_atual(banco) == REVISAO_ANTERIOR
    assert "portal_id" in _colunas(banco, "leitores") and "reader_id" not in _colunas(banco, "leitores")
    assert _portais_dos_leitores(banco)[4] == 2  # a informação continua onde estava


# --- downgrade / roundtrip ----------------------------------------------------------------------


def test_downgrade_restaura_o_portal_do_leitor_e_o_upgrade_de_novo_recalcula(banco):
    _semear_esquema_antigo(banco)
    _migrar(banco, REVISAO_ISS012)
    # topologia nova: o portal 1 ganha uma antena de OUTRO leitor (o leitor 2)
    _sql(banco, "UPDATE antenas SET portal_id = 1 WHERE id = 3")

    processo = _alembic(banco, "downgrade", REVISAO_ANTERIOR)

    assert processo.returncode == 0, _saida(processo)
    assert _portais_dos_leitores(banco) == {1: 1, 2: 1, 3: None, 4: None}
    assert {"portal_id"} <= _colunas(banco, "leitores")
    assert "reader_id" not in _colunas(banco, "leitores") and "portal_id" not in _colunas(banco, "antenas")
    # a FK original volta com o mesmo nome do esquema antigo
    assert "leitores_portal_id_fkey" in {linha[0] for linha in _sql(banco, "SELECT conname FROM pg_constraint")}

    _migrar(banco, REVISAO_ISS012)
    assert _portais_das_antenas(banco) == {1: 1, 2: 1, 3: 1, 4: None}


def test_downgrade_aborta_se_um_leitor_tem_antenas_em_portais_diferentes(banco):
    """Não cabe no modelo antigo (1 leitor -> 1 portal): aborta em vez de escolher um em silêncio."""
    _semear_esquema_antigo(banco)
    _migrar(banco, REVISAO_ISS012)
    _sql(banco, "UPDATE antenas SET portal_id = 2 WHERE id = 2")  # leitor 1: portais 1 e 2

    processo = _alembic(banco, "downgrade", REVISAO_ANTERIOR)

    assert processo.returncode != 0
    saida = _saida(processo)
    assert "portais DIFERENTES" in saida and "leitor 1" in saida
    assert _revisao_atual(banco) == REVISAO_ISS012  # nada foi revertido
    assert "portal_id" not in _colunas(banco, "leitores")
    assert _portais_das_antenas(banco)[2] == 2


def test_migrations_nao_deixam_drift_entre_models_e_esquema(banco):
    _migrar(banco, "head")

    processo = _alembic(banco, "check")

    assert processo.returncode == 0, _saida(processo)
    assert "No new upgrade operations detected" in _saida(processo)


# =========================== segunda migration: porta ativa + timestamps ===========================


def _constraints(url) -> set[str]:
    return {linha[0] for linha in _sql(url, "SELECT conname FROM pg_constraint")}


def _definicao_do_indice(url, nome: str) -> str | None:
    linhas = _sql(url, "SELECT indexdef FROM pg_indexes WHERE indexname = :n", n=nome)
    return linhas[0][0] if linhas else None


NOVA_ANTENA_NA_PORTA_1_DO_LEITOR_1 = (
    "INSERT INTO antenas (leitor_id, porta_numero, zona_associada_id, funcao) VALUES (1, 1, 1, 'saida')"
)


def test_ajustes_trocam_a_unique_pelo_indice_parcial_e_adicionam_timestamps(banco):
    _semear_esquema_antigo(banco)
    _migrar(banco, REVISAO_ISS012)
    assert "uq_antena_por_porta_leitor" in _constraints(banco)  # ainda a UNIQUE total

    _migrar(banco, "head")

    assert "uq_antena_por_porta_leitor" not in _constraints(banco)
    definicao = _definicao_do_indice(banco, "uq_antena_ativa_por_porta_leitor")
    assert definicao is not None and "UNIQUE" in definicao and "WHERE" in definicao and "ativo" in definicao
    # linhas que JÁ existiam receberam timestamps (NOT NULL, default now())
    for tabela in ("leitores", "antenas", "portais"):
        assert {"created_at", "updated_at"} <= _colunas(banco, tabela)
        assert _sql(banco, f"SELECT count(*) FROM {tabela} WHERE created_at IS NULL OR updated_at IS NULL")[0][0] == 0
    # o dado migrado pela primeira revisão continua íntegro
    assert _portais_das_antenas(banco) == {1: 1, 2: 1, 3: 2, 4: None}


def test_indice_parcial_libera_a_porta_da_antena_inativa_mas_barra_duas_ativas(banco):
    _semear_esquema_antigo(banco)
    _migrar(banco, "head")

    # duas ATIVAS na mesma porta: barrado, e com o nome do índice que a aplicação reconhece
    with pytest.raises(IntegrityError) as erro:
        _sql(banco, NOVA_ANTENA_NA_PORTA_1_DO_LEITOR_1)
    assert erro.value.orig.pgcode == "23505"
    assert erro.value.orig.diag.constraint_name == "uq_antena_ativa_por_porta_leitor"

    # inativada a antiga, a porta é liberada
    _sql(banco, "UPDATE antenas SET ativo = false WHERE id = 1")
    _sql(banco, NOVA_ANTENA_NA_PORTA_1_DO_LEITOR_1)
    assert _sql(banco, "SELECT count(*) FROM antenas WHERE leitor_id = 1 AND porta_numero = 1")[0][0] == 2


def test_downgrade_dos_ajustes_restaura_a_unique_total_e_remove_os_timestamps(banco):
    _semear_esquema_antigo(banco)
    _migrar(banco, "head")

    processo = _alembic(banco, "downgrade", REVISAO_ISS012)

    assert processo.returncode == 0, _saida(processo)
    assert _revisao_atual(banco) == REVISAO_ISS012
    assert "uq_antena_por_porta_leitor" in _constraints(banco)
    assert _definicao_do_indice(banco, "uq_antena_ativa_por_porta_leitor") is None
    for tabela in ("leitores", "antenas", "portais"):
        assert not {"created_at", "updated_at"} & _colunas(banco, tabela)
    assert _portais_das_antenas(banco) == {1: 1, 2: 1, 3: 2, 4: None}  # dado intacto


def test_downgrade_dos_ajustes_aborta_se_uma_porta_e_compartilhada_por_inativa_e_ativa(banco):
    """A UNIQUE antiga não admite o que o índice parcial admitia: aborta em vez de apagar linha."""
    _semear_esquema_antigo(banco)
    _migrar(banco, "head")
    _sql(banco, "UPDATE antenas SET ativo = false WHERE id = 1")
    _sql(banco, NOVA_ANTENA_NA_PORTA_1_DO_LEITOR_1)  # a porta 1 do leitor 1 agora tem 2 linhas

    processo = _alembic(banco, "downgrade", REVISAO_ISS012)

    assert processo.returncode != 0
    saida = _saida(processo)
    assert "leitor 1 porta 1" in saida and "UNIQUE total" in saida
    # nada foi revertido nem apagado
    assert _revisao_atual(banco) == REVISAO_ISS012_AJUSTES
    assert _definicao_do_indice(banco, "uq_antena_ativa_por_porta_leitor") is not None
    assert _sql(banco, "SELECT count(*) FROM antenas WHERE leitor_id = 1 AND porta_numero = 1")[0][0] == 2


def test_cadeia_inteira_da_iss012_faz_roundtrip_com_dados_pre_existentes(banco):
    _semear_esquema_antigo(banco)

    _migrar(banco, "head")
    assert _revisao_atual(banco) == REVISAO_ISS012_AJUSTES
    processo = _alembic(banco, "downgrade", REVISAO_ANTERIOR)  # as duas revisões de volta

    assert processo.returncode == 0, _saida(processo)
    assert _revisao_atual(banco) == REVISAO_ANTERIOR
    assert _portais_dos_leitores(banco) == {1: 1, 2: 2, 3: None, 4: None}  # como estava

    _migrar(banco, "head")
    assert _portais_das_antenas(banco) == {1: 1, 2: 1, 3: 2, 4: None}
