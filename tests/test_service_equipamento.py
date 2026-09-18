"""
Testes da camada de serviço da ISS-008, contra Postgres de verdade.

Rodam sem subir a API: o alvo aqui é a regra de negócio, não o contrato
HTTP (esse está em `tests/test_api_equipamento.py`).
"""

from __future__ import annotations

import pytest

from api.service_equipamento import (
    EquipamentoNaoEncontrado,
    IdentificadorDuplicado,
    TipoEquipamentoInvalido,
    atualizar,
    buscar_por_id,
    criar,
    inativar,
    listar,
    reativar,
)
from api.service_tipos_equipamento import criar as criar_tipo
from api.service_tipos_equipamento import inativar as inativar_tipo


def _criar_tipo(db, nome: str = "Maca"):
    return criar_tipo(db, nome=nome)


def test_criar_preenche_normalizado_status_e_timestamps(db):
    tipo = _criar_tipo(db)

    equipamento = criar(
        db,
        nome="Maca do 3o andar",
        tipo_id=tipo.id,
        identificador_interno="  PAT-0001  ",
        descricao="Maca hospitalar padrão",
    )

    assert equipamento.id is not None
    assert equipamento.nome == "Maca do 3o andar"
    assert equipamento.tipo_id == tipo.id
    # Preservado como digitado (só com strip); quem normaliza é a coluna
    # de comparação.
    assert equipamento.identificador_interno == "PAT-0001"
    assert equipamento.identificador_interno_normalizado == "pat-0001"
    assert equipamento.descricao == "Maca hospitalar padrão"
    assert equipamento.status == "ativo"
    assert equipamento.created_at is not None
    assert equipamento.updated_at is not None


def test_criar_sem_descricao_deixa_nulo(db):
    tipo = _criar_tipo(db)

    equipamento = criar(db, nome="Maca", tipo_id=tipo.id, identificador_interno="PAT-0002")

    assert equipamento.descricao is None


def test_criar_com_tipo_inexistente_falha(db):
    with pytest.raises(TipoEquipamentoInvalido) as erro:
        criar(db, nome="Maca", tipo_id=999_999, identificador_interno="PAT-0003")

    assert erro.value.tipo_id == 999_999


def test_criar_com_tipo_inativo_falha(db):
    tipo = _criar_tipo(db)
    inativar_tipo(db, tipo.id)

    with pytest.raises(TipoEquipamentoInvalido):
        criar(db, nome="Maca", tipo_id=tipo.id, identificador_interno="PAT-0004")


def test_criar_com_identificador_duplicado_exato_falha(db):
    tipo = _criar_tipo(db)
    criar(db, nome="Maca 1", tipo_id=tipo.id, identificador_interno="PAT-0005")

    with pytest.raises(IdentificadorDuplicado):
        criar(db, nome="Maca 2", tipo_id=tipo.id, identificador_interno="PAT-0005")


@pytest.mark.parametrize(
    "variacao",
    [
        "pat-0006",
        "PAT-0006",
        "  PAT-0006  ",
        "PAT-0006 ",
        "Pát-0006",
    ],
)
def test_criar_com_identificador_duplicado_so_na_normalizacao_falha(db, variacao):
    tipo = _criar_tipo(db)
    criar(db, nome="Maca", tipo_id=tipo.id, identificador_interno="PAT-0006")

    with pytest.raises(IdentificadorDuplicado):
        criar(db, nome="Outra maca", tipo_id=tipo.id, identificador_interno=variacao)


def test_sessao_continua_utilizavel_depois_de_identificador_duplicado(db):
    tipo = _criar_tipo(db)
    criar(db, nome="Maca", tipo_id=tipo.id, identificador_interno="PAT-0007")

    with pytest.raises(IdentificadorDuplicado):
        criar(db, nome="Maca 2", tipo_id=tipo.id, identificador_interno="pat-0007")

    seguinte = criar(db, nome="Maca 3", tipo_id=tipo.id, identificador_interno="PAT-0008")
    assert seguinte.id is not None


def test_buscar_por_id_traz_o_tipo_carregado(db):
    tipo = _criar_tipo(db, nome="Cadeira de rodas")
    equipamento = criar(db, nome="Cadeira 1", tipo_id=tipo.id, identificador_interno="PAT-0009")

    encontrado = buscar_por_id(db, equipamento.id)

    assert encontrado.id == equipamento.id
    # `tipo` precisa estar carregado sem lazy-load: acessar o atributo não
    # pode disparar uma query nova na mesma sessão de teste. Não dá para
    # provar "zero query" de dentro do teste sem instrumentar o engine,
    # mas o acesso abaixo, se o joinedload não tivesse funcionado, ainda
    # teria sucesso (lazy load também resolveria) — o que este teste
    # garante é o contrato observável: `tipo.nome` disponível e correto.
    assert encontrado.tipo.nome == "Cadeira de rodas"


def test_buscar_por_id_inexistente_levanta_erro_de_dominio(db):
    with pytest.raises(EquipamentoNaoEncontrado):
        buscar_por_id(db, 999_999)


def test_atualizar_nome_e_tipo(db):
    tipo_a = _criar_tipo(db, nome="Maca")
    tipo_b = _criar_tipo(db, nome="Cadeira de rodas")
    equipamento = criar(db, nome="Maca 1", tipo_id=tipo_a.id, identificador_interno="PAT-0010")

    atualizado = atualizar(db, equipamento.id, nome="Maca renomeada", tipo_id=tipo_b.id)

    assert atualizado.nome == "Maca renomeada"
    assert atualizado.tipo_id == tipo_b.id
    assert atualizado.tipo.nome == "Cadeira de rodas"


def test_atualizar_identificador_nao_e_aceito_pelo_parametro(db):
    """
    O serviço nem expõe parâmetro `identificador_interno` em `atualizar` —
    este teste documenta o contrato: chamar `atualizar` não tem como
    tocar o identificador, porque a assinatura não aceita.
    """
    import inspect

    assinatura = inspect.signature(atualizar)
    assert "identificador_interno" not in assinatura.parameters


def test_atualizar_para_tipo_inexistente_falha(db):
    tipo = _criar_tipo(db)
    equipamento = criar(db, nome="Maca", tipo_id=tipo.id, identificador_interno="PAT-0011")

    with pytest.raises(TipoEquipamentoInvalido):
        atualizar(db, equipamento.id, tipo_id=999_999)


def test_atualizar_para_tipo_inativo_falha(db):
    tipo_a = _criar_tipo(db, nome="Maca")
    tipo_b = _criar_tipo(db, nome="Cadeira de rodas")
    inativar_tipo(db, tipo_b.id)
    equipamento = criar(db, nome="Maca", tipo_id=tipo_a.id, identificador_interno="PAT-0012")

    with pytest.raises(TipoEquipamentoInvalido):
        atualizar(db, equipamento.id, tipo_id=tipo_b.id)

    # A tentativa bloqueada não pode ter efeito colateral.
    assert buscar_por_id(db, equipamento.id).tipo_id == tipo_a.id


def test_atualizar_sem_mandar_descricao_preserva_a_atual(db):
    tipo = _criar_tipo(db)
    equipamento = criar(
        db,
        nome="Maca",
        tipo_id=tipo.id,
        identificador_interno="PAT-0013",
        descricao="descrição original",
    )

    atualizado = atualizar(db, equipamento.id, nome="Maca renomeada", descricao_informada=False)

    assert atualizado.nome == "Maca renomeada"
    assert atualizado.descricao == "descrição original"


def test_atualizar_mandando_descricao_nula_limpa_o_campo(db):
    tipo = _criar_tipo(db)
    equipamento = criar(
        db,
        nome="Maca",
        tipo_id=tipo.id,
        identificador_interno="PAT-0014",
        descricao="descrição original",
    )

    atualizado = atualizar(db, equipamento.id, descricao=None, descricao_informada=True)

    assert atualizado.descricao is None


def test_atualizar_inexistente_levanta_erro_de_dominio(db):
    with pytest.raises(EquipamentoNaoEncontrado):
        atualizar(db, 999_999, nome="Qualquer")


def test_listar_paginado_calcula_total_e_pages(db):
    tipo = _criar_tipo(db)
    for indice in range(25):
        criar(db, nome=f"Equip {indice:02d}", tipo_id=tipo.id, identificador_interno=f"PAT-{indice:04d}")

    primeira = listar(db, page=1, size=10)
    assert primeira.total == 25
    assert primeira.pages == 3
    assert len(primeira.items) == 10

    ultima = listar(db, page=3, size=10)
    assert len(ultima.items) == 5
    assert {item.id for item in primeira.items}.isdisjoint({item.id for item in ultima.items})


def test_listar_banco_vazio(db):
    pagina = listar(db)

    assert pagina.total == 0
    assert pagina.pages == 0
    assert pagina.items == []


def test_listar_esconde_inativos_por_padrao(db):
    tipo = _criar_tipo(db)
    ativo = criar(db, nome="Maca ativa", tipo_id=tipo.id, identificador_interno="PAT-0015")
    inativo = criar(db, nome="Maca inativa", tipo_id=tipo.id, identificador_interno="PAT-0016")
    inativar(db, inativo.id)

    padrao = listar(db)
    assert [item.id for item in padrao.items] == [ativo.id]
    assert padrao.total == 1

    com_inativos = listar(db, incluir_inativos=True)
    assert com_inativos.total == 2


def test_listar_traz_tipo_carregado_em_cada_item(db):
    tipo = _criar_tipo(db, nome="Cadeira de rodas")
    criar(db, nome="Cadeira 1", tipo_id=tipo.id, identificador_interno="PAT-0017")

    pagina = listar(db)

    assert pagina.items[0].tipo.nome == "Cadeira de rodas"


def test_inativar_marca_status_mas_nao_apaga_a_linha(db):
    tipo = _criar_tipo(db)
    equipamento = criar(db, nome="Maca", tipo_id=tipo.id, identificador_interno="PAT-0018")

    inativado = inativar(db, equipamento.id)

    assert inativado.status == "inativo"
    # A linha continua existindo: buscar por id depois de inativar não
    # pode levantar EquipamentoNaoEncontrado — é o ponto central de "baixa
    # lógica, nunca DELETE".
    assert buscar_por_id(db, equipamento.id).status == "inativo"


def test_inativar_nao_bloqueia_por_nenhum_motivo(db):
    """
    Diferente de `tipos_equipamento.inativar`: aqui não existe conceito de
    "em uso" — inativar um equipamento não tem nenhuma dependência que
    poderia bloquear a operação.
    """
    tipo = _criar_tipo(db)
    equipamento = criar(db, nome="Maca", tipo_id=tipo.id, identificador_interno="PAT-0019")

    # Não levanta nenhuma exceção.
    inativar(db, equipamento.id)


def test_inativar_duas_vezes_e_idempotente(db):
    tipo = _criar_tipo(db)
    equipamento = criar(db, nome="Maca", tipo_id=tipo.id, identificador_interno="PAT-0020")

    inativar(db, equipamento.id)
    segunda_vez = inativar(db, equipamento.id)

    assert segunda_vez.status == "inativo"


def test_inativar_inexistente_levanta_erro_de_dominio(db):
    with pytest.raises(EquipamentoNaoEncontrado):
        inativar(db, 999_999)


def test_reativar_devolve_o_equipamento_para_a_listagem(db):
    tipo = _criar_tipo(db)
    equipamento = criar(db, nome="Maca", tipo_id=tipo.id, identificador_interno="PAT-0021")
    inativar(db, equipamento.id)

    reativado = reativar(db, equipamento.id)

    assert reativado.status == "ativo"
    assert [item.id for item in listar(db).items] == [equipamento.id]


def test_reativar_duas_vezes_e_idempotente(db):
    tipo = _criar_tipo(db)
    equipamento = criar(db, nome="Maca", tipo_id=tipo.id, identificador_interno="PAT-0022")

    reativar(db, equipamento.id)
    assert reativar(db, equipamento.id).status == "ativo"
