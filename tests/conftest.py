"""Banco explicitamente descartável; fixtures nunca usam URLs da aplicação/Neon."""

import os
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from db.models import Andar, Antena, Base, Leitor, Setor, Zona


@pytest.fixture
def pg_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("exige TEST_DATABASE_URL de PostgreSQL descartável")
    engine = create_engine(url, hide_parameters=True)
    schema = "iss006_" + uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(isolated)
        yield isolated
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


@pytest.fixture
def topology(pg_engine):
    with pg_engine.begin() as connection:
        floor = connection.execute(Andar.__table__.insert().values(nome="teste").returning(Andar.id)).scalar_one()
        sector = connection.execute(Setor.__table__.insert().values(andar_id=floor, nome="teste").returning(Setor.id)).scalar_one()
        zone = connection.execute(Zona.__table__.insert().values(setor_id=sector, nome="teste").returning(Zona.id)).scalar_one()
        reader = connection.execute(Leitor.__table__.insert().values(
            reader_id="reader-01", identificador_serial="serial-independente",
            fabricante="teste", modelo="teste").returning(Leitor.id)).scalar_one()
        antenna = connection.execute(Antena.__table__.insert().values(
            leitor_id=reader, porta_numero=1, zona_associada_id=zone,
            funcao="indefinido").returning(Antena.id)).scalar_one()
    return {"reader": reader, "antenna": antenna, "zone": zone}
