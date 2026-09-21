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
    assert len(inspector.get_table_names()) == 17
    columns = {c["name"]: c for c in inspector.get_columns("leituras_brutas")}
    assert columns["event_id"]["type"].length == 71
    assert not columns["event_id"]["nullable"]
    assert columns["rssi"]["nullable"]
    assert str(columns["dados_origem"]["type"]) == "JSONB"
    assert any(c["column_names"] == ["event_id"] for c in inspector.get_unique_constraints("leituras_brutas"))
    assert any(c["column_names"] == ["reader_id"] for c in inspector.get_unique_constraints("leitores"))
    with pg_empty_schema.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "da436f7c75b3"


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
