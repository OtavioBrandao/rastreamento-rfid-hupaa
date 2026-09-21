"""Testes do seed idempotente e configurável do setor piloto (ISS-011)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from api.seed_localizacao_piloto import (
    ConfigLocalizacaoPiloto,
    _config_da_linha_de_comando,
    semear,
)
from api.service_localizacao import (
    PaiInvalido,
    criar_andar,
    criar_setor,
    inativar_andar,
)
from db.models import Andar, Setor, Zona


def _contar(db, modelo) -> int:
    return db.scalar(select(func.count()).select_from(modelo))


def test_seed_cria_os_tres_niveis(db):
    resultado = semear(db)

    config = ConfigLocalizacaoPiloto()
    assert resultado.andar_criado and resultado.setor_criado
    assert resultado.zonas_criadas == list(config.zonas)
    assert resultado.total_criado == 2 + len(config.zonas)

    andar = db.scalar(select(Andar))
    setor = db.scalar(select(Setor))
    assert (andar.nome, setor.nome) == (config.andar, config.setor)
    assert setor.andar_id == andar.id
    zonas = db.scalars(select(Zona).order_by(Zona.id)).all()
    assert [z.nome for z in zonas] == list(config.zonas)
    assert all(z.setor_id == setor.id for z in zonas)


def test_seed_e_idempotente_em_cada_nivel(db):
    semear(db)
    segunda = semear(db)

    assert segunda.total_criado == 0
    assert (_contar(db, Andar), _contar(db, Setor)) == (1, 1)
    assert _contar(db, Zona) == len(ConfigLocalizacaoPiloto().zonas)


def test_seed_completa_so_o_que_falta(db):
    """Andar e setor já existem; só as zonas são criadas."""
    config = ConfigLocalizacaoPiloto()
    andar = criar_andar(db, nome=config.andar)
    criar_setor(db, andar_id=andar.id, nome=config.setor)

    resultado = semear(db, config)

    assert not resultado.andar_criado and not resultado.setor_criado
    assert resultado.zonas_criadas == list(config.zonas)


def test_seed_reconhece_variacao_de_acento_caixa_e_espaco(db):
    """A checagem é por nome_normalizado, não por nome exato."""
    criar_andar(db, nome="4o  ANDAR")

    resultado = semear(db, ConfigLocalizacaoPiloto(andar="4º Andar"))

    assert not resultado.andar_criado
    assert _contar(db, Andar) == 1


def test_seed_e_configuravel(db):
    config = ConfigLocalizacaoPiloto(
        andar="5º Andar", setor="UTI Adulto", zonas=("Box 1", "Box 2")
    )

    resultado = semear(db, config)

    assert resultado.zonas_criadas == ["Box 1", "Box 2"]
    assert db.scalar(select(Andar.nome)) == "5º Andar"
    assert db.scalar(select(Setor.nome)) == "UTI Adulto"
    assert {z.nome for z in db.scalars(select(Zona))} == {"Box 1", "Box 2"}


def test_seed_configuracoes_diferentes_convivem(db):
    """Setor com o mesmo nome em andares diferentes NÃO colide (escopo)."""
    semear(db, ConfigLocalizacaoPiloto(andar="3º Andar", setor="Enfermaria", zonas=("Leito 01",)))
    semear(db, ConfigLocalizacaoPiloto(andar="4º Andar", setor="Enfermaria", zonas=("Leito 01",)))

    assert (_contar(db, Andar), _contar(db, Setor), _contar(db, Zona)) == (2, 2, 2)


def test_seed_nao_duplica_zona_repetida_dentro_da_propria_config(db):
    config = ConfigLocalizacaoPiloto(zonas=("Leito 01", "leito  01", "Leito 02"))

    resultado = semear(db, config)

    assert resultado.zonas_criadas == ["Leito 01", "Leito 02"]
    assert _contar(db, Zona) == 2


def test_seed_com_andar_existente_inativo_e_setor_novo_falha_sem_reativar(db):
    andar = criar_andar(db, nome="4º Andar")
    inativar_andar(db, andar.id)

    with pytest.raises(PaiInvalido):
        semear(db, ConfigLocalizacaoPiloto(andar="4º Andar"))

    assert db.get(Andar, andar.id).ativo is False


@pytest.mark.parametrize(
    "kwargs",
    [{"andar": "  "}, {"setor": ""}, {"zonas": ()}, {"zonas": ("Leito 01", "  ")}],
)
def test_config_invalida_e_rejeitada(kwargs):
    with pytest.raises(ValueError):
        ConfigLocalizacaoPiloto(**kwargs)


def test_linha_de_comando_sobrescreve_e_mantem_defaults():
    padrao = ConfigLocalizacaoPiloto()

    sem_args = _config_da_linha_de_comando([])
    assert sem_args == padrao

    com_args = _config_da_linha_de_comando(
        ["--andar", "5º Andar", "--setor", "UTI", "--zona", "Box 1", "--zona", "Box 2"]
    )
    assert com_args == ConfigLocalizacaoPiloto(andar="5º Andar", setor="UTI", zonas=("Box 1", "Box 2"))

    so_andar = _config_da_linha_de_comando(["--andar", "5º Andar"])
    assert (so_andar.setor, so_andar.zonas) == (padrao.setor, padrao.zonas)
