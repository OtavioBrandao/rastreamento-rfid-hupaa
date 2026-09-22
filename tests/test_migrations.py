"""Ciclo CI em schema descartável próprio, nunca downgrade no schema público."""

from conftest import migration_config
from sqlalchemy import inspect, text

from alembic import command


def test_empty_upgrade_repeat_downgrade_reupgrade(pg_empty_schema):
    config = migration_config()
    for target in ("head", "head"):
        command.upgrade(config, target)
    command.downgrade(config, "base")
    assert inspect(pg_empty_schema).get_table_names() == ["alembic_version"]
    command.upgrade(config, "head")
    command.check(config)
    inspector = inspect(pg_empty_schema)
    assert len(inspector.get_table_names()) == 18
    columns = {c["name"]: c for c in inspector.get_columns("leituras_brutas")}
    assert columns["event_id"]["type"].length == 71
    assert not columns["event_id"]["nullable"]
    assert columns["rssi"]["nullable"]
    assert str(columns["dados_origem"]["type"]) == "JSONB"
    assert any(c["column_names"] == ["event_id"] for c in inspector.get_unique_constraints("leituras_brutas"))
    assert any(c["column_names"] == ["reader_id"] for c in inspector.get_unique_constraints("leitores"))
    assert any(
        index["name"] == "uq_passagem_evidencias" and index["unique"]
        for index in inspector.get_indexes("passagens")
    )
    with pg_empty_schema.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "9d0116a01600"


def test_existing_reader_receives_serial_as_initial_reader_id(pg_empty_schema):
    """Sob ISS-012, reader_id é NOT NULL e inicializado a partir do serial único."""
    config = migration_config()
    command.upgrade(config, "44ef89b10f17")
    with pg_empty_schema.begin() as connection:
        connection.execute(text("INSERT INTO leitores (fabricante, modelo, identificador_serial) "
                                "VALUES ('teste', 'teste', 'reader-01')"))
    command.upgrade(config, "head")
    with pg_empty_schema.connect() as connection:
        assert connection.execute(text("SELECT reader_id, identificador_serial FROM leitores")).one() == ("reader-01", "reader-01")


def test_iss015_unique_index_downgrade_and_reupgrade(pg_empty_schema):
    config = migration_config()
    command.upgrade(config, "head")
    assert any(
        item["name"] == "uq_passagem_evidencias"
        for item in inspect(pg_empty_schema).get_indexes("passagens")
    )
    command.downgrade(config, "68e5a26c2e17")
    assert not any(
        item["name"] == "uq_passagem_evidencias"
        for item in inspect(pg_empty_schema).get_indexes("passagens")
    )
    command.upgrade(config, "head")
    assert any(
        item["name"] == "uq_passagem_evidencias"
        for item in inspect(pg_empty_schema).get_indexes("passagens")
    )


def test_iss016_upgrade_preserves_pending_passage_and_roundtrip(pg_empty_schema):
    config = migration_config()
    command.upgrade(config, "4b751b0e9015")
    with pg_empty_schema.begin() as connection:
        connection.execute(text(
            "INSERT INTO andares (id,nome,nome_normalizado) VALUES (1,'a','a')"
        ))
        connection.execute(text(
            "INSERT INTO setores (id,andar_id,nome,nome_normalizado) VALUES (1,1,'s','s')"
        ))
        connection.execute(text(
            "INSERT INTO zonas (id,setor_id,nome,nome_normalizado) "
            "VALUES (1,1,'z1','z1'),(2,1,'z2','z2')"
        ))
        connection.execute(text(
            "INSERT INTO portais (id,nome,zona_a_id,zona_b_id) VALUES (1,'p',1,2)"
        ))
        connection.execute(text(
            "INSERT INTO leitores (id,reader_id,fabricante,modelo,identificador_serial) "
            "VALUES (1,'reader-1','f','m','serial-1')"
        ))
        connection.execute(text(
            "INSERT INTO antenas (id,leitor_id,porta_numero,zona_associada_id,funcao) "
            "VALUES (1,1,1,1,'entrada'),(2,1,2,2,'saida')"
        ))
        connection.execute(text(
            "INSERT INTO leituras_brutas (id,event_id,antena_id,epc,lido_em) "
            "VALUES (1,'e1',1,'EPC','2026-09-22 12:00:00+00'),"
            "(2,'e2',2,'EPC','2026-09-22 12:00:01+00')"
        ))
        connection.execute(text(
            "INSERT INTO passagens (id,epc,portal_id,antena_origem_id,antena_destino_id,"
            "leitura_origem_id,leitura_destino_id,detectada_em,direcao) "
            "VALUES (1,'EPC',1,1,2,1,2,'2026-09-22 12:00:01+00',NULL)"
        ))
    command.upgrade(config, "head")
    with pg_empty_schema.connect() as connection:
        assert connection.execute(text(
            "SELECT direcao,direcao_status,zona_origem_id,zona_destino_id "
            "FROM passagens WHERE id=1"
        )).one() == (None, None, None, None)
    columns = {item["name"] for item in inspect(pg_empty_schema).get_columns("passagens")}
    assert {"direcao_status", "direcao_regra", "zona_origem_id", "zona_destino_id"} <= columns
    command.downgrade(config, "4b751b0e9015")
    with pg_empty_schema.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM passagens")) == 1
    command.upgrade(config, "head")
    with pg_empty_schema.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM passagens")) == 1
