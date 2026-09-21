"""
Testes da camada de serviço da ISS-009, contra Postgres de verdade.

Rodam sem subir a API: o alvo aqui é a regra de negócio, não o contrato
HTTP (esse está em `tests/test_api_tipos_equipamento.py`).
"""

from __future__ import annotations

import pytest

from api.normalizacao import normalizar_nome
from api.service_tipos_equipamento import (
    NomeDuplicado,
    TipoEquipamentoEmUso,
    TipoEquipamentoNaoEncontrado,
    atualizar,
    buscar_por_id,
    criar,
    inativar,
    listar,
    reativar,
)
from db.models import Equipamento


def _criar_equipamento(session, tipo_id: int, identificador: str = "EQ-001") -> Equipamento:
    # Cria a linha direto pelo model, sem passar por
    # `api.service_equipamento` — de propósito, para não acoplar este
    # teste de `tipos_equipamento` ao serviço de outra issue.
    # `identificador_interno_normalizado` é NOT NULL (ISS-008), então
    # precisa ser preenchido aqui igual o serviço faria.
    equipamento = Equipamento(
        nome="Maca do 3o andar",
        tipo_id=tipo_id,
        identificador_interno=identificador,
        identificador_interno_normalizado=normalizar_nome(identificador),
    )
    session.add(equipamento)
    session.commit()
    return equipamento


def test_criar_preenche_normalizado_ativo_e_timestamps(db):
    tipo = criar(db, nome="  Cadeira de Rodas ", descricao="Cadeira manual")

    assert tipo.id is not None
    # O nome é preservado como digitado (só com strip); quem normaliza é
    # a coluna de comparação.
    assert tipo.nome == "Cadeira de Rodas"
    assert tipo.nome_normalizado == "cadeira de rodas"
    assert tipo.descricao == "Cadeira manual"
    assert tipo.ativo is True
    assert tipo.created_at is not None
    assert tipo.updated_at is not None


def test_criar_sem_descricao_deixa_nulo(db):
    tipo = criar(db, nome="Maca")

    assert tipo.descricao is None


def test_criar_com_nome_identico_falha(db):
    criar(db, nome="Maca")

    with pytest.raises(NomeDuplicado):
        criar(db, nome="Maca")


@pytest.mark.parametrize(
    "variacao",
    [
        "cadeira de rodas",
        "CADEIRA DE RODAS",
        "Cadeira De Rodas",
        "  Cadeira de Rodas  ",
        "Cadeira  de   Rodas",
        "Cadeira de Ródas",
    ],
)
def test_criar_com_nome_duplicado_so_na_normalizacao_falha(db, variacao):
    criar(db, nome="Cadeira de rodas")

    with pytest.raises(NomeDuplicado):
        criar(db, nome=variacao)


def test_sessao_continua_utilizavel_depois_de_nome_duplicado(db):
    """O rollback do serviço tem de deixar a sessão viva para o próximo uso."""
    criar(db, nome="Maca")

    with pytest.raises(NomeDuplicado):
        criar(db, nome="maca")

    seguinte = criar(db, nome="Cadeira de rodas")
    assert seguinte.id is not None


@pytest.mark.parametrize(
    "outro_nome",
    ["Maca infantil", "Cadeira de banho", "Carrinho de emergência"],
)
def test_nomes_de_fato_diferentes_nao_colidem(db, outro_nome):
    criar(db, nome="Cadeira de rodas")

    outro = criar(db, nome=outro_nome)
    assert outro.id is not None


def test_buscar_por_id_devolve_o_tipo(db):
    tipo = criar(db, nome="Maca")

    assert buscar_por_id(db, tipo.id).id == tipo.id


def test_buscar_por_id_inexistente_levanta_erro_de_dominio(db):
    with pytest.raises(TipoEquipamentoNaoEncontrado):
        buscar_por_id(db, 999_999)


def test_atualizar_nome_e_descricao(db):
    tipo = criar(db, nome="Maca", descricao="descrição antiga")

    atualizado = atualizar(
        db,
        tipo.id,
        nome="Maca Hospitalar",
        descricao="descrição nova",
        veio_descricao=True,
    )

    assert atualizado.nome == "Maca Hospitalar"
    assert atualizado.nome_normalizado == "maca hospitalar"
    assert atualizado.descricao == "descrição nova"


def test_atualizar_sem_mandar_descricao_preserva_a_atual(db):
    tipo = criar(db, nome="Maca", descricao="descrição original")

    atualizado = atualizar(db, tipo.id, nome="Maca Hospitalar", veio_descricao=False)

    assert atualizado.nome == "Maca Hospitalar"
    assert atualizado.descricao == "descrição original"


def test_atualizar_mandando_descricao_nula_limpa_o_campo(db):
    tipo = criar(db, nome="Maca", descricao="descrição original")

    atualizado = atualizar(db, tipo.id, descricao=None, veio_descricao=True)

    assert atualizado.descricao is None


def test_atualizar_para_nome_ja_usado_falha(db):
    criar(db, nome="Maca")
    outro = criar(db, nome="Cadeira de rodas")

    with pytest.raises(NomeDuplicado):
        atualizar(db, outro.id, nome="MACA")


def test_atualizar_inexistente_levanta_erro_de_dominio(db):
    with pytest.raises(TipoEquipamentoNaoEncontrado):
        atualizar(db, 999_999, nome="Qualquer")


def test_listar_paginado_calcula_total_e_pages(db):
    for indice in range(25):
        criar(db, nome=f"Tipo {indice:02d}")

    primeira = listar(db, page=1, size=10)
    assert primeira.total == 25
    assert primeira.pages == 3
    assert primeira.page == 1
    assert primeira.size == 10
    assert len(primeira.items) == 10

    ultima = listar(db, page=3, size=10)
    assert len(ultima.items) == 5
    # Páginas não podem se sobrepor: a ordenação precisa ser estável.
    assert {tipo.id for tipo in primeira.items}.isdisjoint({tipo.id for tipo in ultima.items})


def test_listar_banco_vazio(db):
    pagina = listar(db)

    assert pagina.total == 0
    assert pagina.pages == 0
    assert pagina.items == []


def test_listar_esconde_inativos_por_padrao(db):
    ativo = criar(db, nome="Maca")
    inativo = criar(db, nome="Cadeira de rodas")
    inativar(db, inativo.id)

    padrao = listar(db)
    assert [tipo.id for tipo in padrao.items] == [ativo.id]
    assert padrao.total == 1

    com_inativos = listar(db, incluir_inativos=True)
    assert com_inativos.total == 2


def test_inativar_tipo_sem_uso(db):
    tipo = criar(db, nome="Maca")

    inativado = inativar(db, tipo.id)

    assert inativado.ativo is False


def test_inativar_tipo_referenciado_por_equipamento_falha(db):
    tipo = criar(db, nome="Maca")
    _criar_equipamento(db, tipo.id)

    with pytest.raises(TipoEquipamentoEmUso) as erro:
        inativar(db, tipo.id)

    assert erro.value.total_equipamentos == 1
    # A proteção não pode ter efeito colateral: o tipo segue ativo.
    assert buscar_por_id(db, tipo.id).ativo is True


def test_inativar_duas_vezes_e_idempotente(db):
    tipo = criar(db, nome="Maca")

    inativar(db, tipo.id)
    segunda_vez = inativar(db, tipo.id)

    assert segunda_vez.ativo is False


def test_inativar_inexistente_levanta_erro_de_dominio(db):
    with pytest.raises(TipoEquipamentoNaoEncontrado):
        inativar(db, 999_999)


def test_reativar_devolve_o_tipo_para_a_listagem(db):
    tipo = criar(db, nome="Maca")
    inativar(db, tipo.id)

    reativado = reativar(db, tipo.id)

    assert reativado.ativo is True
    assert [item.id for item in listar(db).items] == [tipo.id]


def test_reativar_duas_vezes_e_idempotente(db):
    tipo = criar(db, nome="Maca")

    reativar(db, tipo.id)
    assert reativar(db, tipo.id).ativo is True
