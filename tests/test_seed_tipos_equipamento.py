"""Testes do seed idempotente da ISS-009."""

from __future__ import annotations

from sqlalchemy import func, select

from api.normalizacao import normalizar_nome
from api.seed_tipos_equipamento import TIPOS_PADRAO, semear
from api.service_tipos_equipamento import criar
from db.models import TipoEquipamento


def _nomes_no_banco(session) -> set[str]:
    return set(session.scalars(select(TipoEquipamento.nome)).all())


def test_seed_cria_os_tres_tipos_padrao(db):
    criados = semear(db)

    assert len(criados) == 3
    assert _nomes_no_banco(db) == set(TIPOS_PADRAO)


def test_seed_rodado_duas_vezes_nao_duplica(db):
    semear(db)
    criados_na_segunda_vez = semear(db)

    assert criados_na_segunda_vez == []
    assert db.scalar(select(func.count()).select_from(TipoEquipamento)) == 3


def test_seed_nao_duplica_variacao_de_acento_ou_caixa(db):
    """
    O ponto da checagem por `nome_normalizado`: se alguém já cadastrou
    "carrinho de emergencia" na mão, o seed tem de reconhecer que é o
    mesmo tipo, não tentar inserir e estourar no UNIQUE.
    """
    criar(db, nome="carrinho de emergencia")

    criados = semear(db)

    assert len(criados) == 2
    assert db.scalar(select(func.count()).select_from(TipoEquipamento)) == 3
    normalizados = set(db.scalars(select(TipoEquipamento.nome_normalizado)).all())
    assert normalizados == {normalizar_nome(nome) for nome in TIPOS_PADRAO}
