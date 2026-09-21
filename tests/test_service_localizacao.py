"""
Testes da camada de serviço da ISS-011 (hierarquia física), contra Postgres
de verdade. Rodam sem subir a API: o alvo aqui é a regra de negócio. O
contrato HTTP está em `tests/test_api_localizacao.py`.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from api.service_equipamento import criar as criar_equipamento
from api.service_equipamento import inativar as inativar_equipamento
from api.service_localizacao import (
    AndarNaoEncontrado,
    NomeDuplicado,
    PaiInativo,
    PaiInvalido,
    SetorNaoEncontrado,
    TemFilhosAtivos,
    ZonaEmUso,
    ZonaNaoEncontrada,
    arvore_completa,
    arvore_do_andar,
    atualizar_andar,
    atualizar_setor,
    atualizar_zona,
    buscar_andar_por_id,
    buscar_setor_por_id,
    buscar_zona_por_id,
    criar_andar,
    criar_setor,
    criar_zona,
    inativar_andar,
    inativar_setor,
    inativar_zona,
    listar_andares,
    listar_setores,
    listar_zonas,
    reativar_andar,
    reativar_setor,
    reativar_zona,
)
from api.service_tipos_equipamento import criar as criar_tipo
from db.models import Andar, Antena, HistoricoMovimentacao, Leitor, Portal, Setor, TipoEquipamento

_CONTADOR = itertools.count(1)


# --- helpers ------------------------------------------------------------------------


def _hierarquia(db, andar="4º Andar", setor="Ala Norte", zona="Leito 01"):
    a = criar_andar(db, nome=andar)
    s = criar_setor(db, andar_id=a.id, nome=setor)
    z = criar_zona(db, setor_id=s.id, nome=zona)
    return a, s, z


def _equipamento(db, ultima_zona_id=None, ativo=True):
    # Reaproveita UM tipo: criar "Maca" a cada chamada colidiria com o UNIQUE
    # de nome_normalizado (ISS-009) quando um teste precisa de 2+ equipamentos.
    tipo = db.scalar(select(TipoEquipamento).where(TipoEquipamento.nome_normalizado == "maca"))
    if tipo is None:
        tipo = criar_tipo(db, nome="Maca")
    equipamento = criar_equipamento(
        db,
        nome="Maca de teste",
        tipo_id=tipo.id,
        identificador_interno=f"LOC-{next(_CONTADOR):04d}",
    )
    if not ativo:
        equipamento = inativar_equipamento(db, equipamento.id)
    if ultima_zona_id is not None:
        equipamento.ultima_zona_id = ultima_zona_id
        db.commit()
    return equipamento


def _portal(db, zona_a_id, zona_b_id):
    portal = Portal(nome="Portal de teste", zona_a_id=zona_a_id, zona_b_id=zona_b_id)
    db.add(portal)
    db.commit()
    return portal


def _antena(db, zona_id):
    leitor = Leitor(
        fabricante="Identix", modelo="EZ700", identificador_serial=f"SN-{next(_CONTADOR):04d}"
    )
    db.add(leitor)
    db.flush()
    antena = Antena(leitor_id=leitor.id, porta_numero=1, zona_associada_id=zona_id, funcao="entrada")
    db.add(antena)
    db.commit()
    return antena


def _historico(db, zona_origem_id, zona_destino_id):
    equipamento = _equipamento(db)
    # registro ANTIGO de propósito: a zona não pode ser inativada mesmo assim.
    registro = HistoricoMovimentacao(
        equipamento_id=equipamento.id,
        zona_origem_id=zona_origem_id,
        zona_destino_id=zona_destino_id,
        origem_registro="correcao_manual",
        registrado_em=datetime.now(timezone.utc) - timedelta(days=400),
    )
    db.add(registro)
    db.commit()
    return registro


# --- duplicidade por nome normalizado, no escopo certo --------------------------------


@pytest.mark.parametrize("variacao", ["4º Andar", "4o andar", "4O  ANDAR", "  4º  andar  "])
def test_andar_duplicado_por_normalizacao_falha(db, variacao):
    criar_andar(db, nome="4º Andar")

    with pytest.raises(NomeDuplicado) as erro:
        criar_andar(db, nome=variacao)

    assert erro.value.nivel == "andar"


@pytest.mark.parametrize("variacao", ["Ala Norte", "ala  norte", "ALA NORTE", " Álá Nórte "])
def test_setor_duplicado_no_mesmo_andar_por_normalizacao_falha(db, variacao):
    andar = criar_andar(db, nome="4º Andar")
    criar_setor(db, andar_id=andar.id, nome="Ala Norte")

    with pytest.raises(NomeDuplicado) as erro:
        criar_setor(db, andar_id=andar.id, nome=variacao)

    assert erro.value.nivel == "setor"


@pytest.mark.parametrize("variacao", ["Leito 01", "leito  01", "LEITO 01", " Leito 01 "])
def test_zona_duplicada_no_mesmo_setor_por_normalizacao_falha(db, variacao):
    _, setor, _ = _hierarquia(db)

    with pytest.raises(NomeDuplicado) as erro:
        criar_zona(db, setor_id=setor.id, nome=variacao)

    assert erro.value.nivel == "zona"


def test_setor_com_mesmo_nome_em_andares_diferentes_nao_colide(db):
    andar_3 = criar_andar(db, nome="3º Andar")
    andar_4 = criar_andar(db, nome="4º Andar")

    no_3 = criar_setor(db, andar_id=andar_3.id, nome="Enfermaria")
    no_4 = criar_setor(db, andar_id=andar_4.id, nome="enfermaria")

    assert no_3.id != no_4.id
    assert no_3.nome_normalizado == no_4.nome_normalizado == "enfermaria"


def test_zona_com_mesmo_nome_em_setores_diferentes_nao_colide(db):
    andar = criar_andar(db, nome="4º Andar")
    setor_a = criar_setor(db, andar_id=andar.id, nome="Ala Norte")
    setor_b = criar_setor(db, andar_id=andar.id, nome="Ala Sul")

    zona_a = criar_zona(db, setor_id=setor_a.id, nome="Leito 01")
    zona_b = criar_zona(db, setor_id=setor_b.id, nome="LEITO 01")

    assert zona_a.id != zona_b.id


def test_sessao_continua_utilizavel_depois_de_nome_duplicado(db):
    criar_andar(db, nome="4º Andar")

    with pytest.raises(NomeDuplicado):
        criar_andar(db, nome="4o andar")

    assert criar_andar(db, nome="5º Andar").id is not None


def test_criar_preenche_campos_e_faz_strip(db):
    andar = criar_andar(
        db, nome="  4º Andar ", descricao="Internação", referencia_planta="Planta A-4"
    )

    assert andar.nome == "4º Andar"
    assert andar.nome_normalizado == "4o andar"
    assert andar.descricao == "Internação"
    assert andar.referencia_planta == "Planta A-4"
    assert andar.ativo is True
    assert andar.created_at is not None and andar.updated_at is not None


# --- pai inexistente ou inativo ---------------------------------------------------------


def test_criar_setor_com_andar_inexistente_falha(db):
    with pytest.raises(PaiInvalido) as erro:
        criar_setor(db, andar_id=999_999, nome="Ala Norte")

    assert erro.value.nivel_pai == "andar"
    assert "não existe" in erro.value.motivo


def test_criar_setor_com_andar_inativo_falha(db):
    andar = criar_andar(db, nome="4º Andar")
    inativar_andar(db, andar.id)

    with pytest.raises(PaiInvalido) as erro:
        criar_setor(db, andar_id=andar.id, nome="Ala Norte")

    assert "inativo" in erro.value.motivo


def test_criar_zona_com_setor_inexistente_falha(db):
    with pytest.raises(PaiInvalido) as erro:
        criar_zona(db, setor_id=999_999, nome="Leito 01")

    assert erro.value.nivel_pai == "setor"


def test_criar_zona_com_setor_inativo_falha(db):
    _, setor, zona = _hierarquia(db)
    inativar_zona(db, zona.id)
    inativar_setor(db, setor.id)

    with pytest.raises(PaiInvalido) as erro:
        criar_zona(db, setor_id=setor.id, nome="Leito 02")

    assert "inativo" in erro.value.motivo


# --- inativação de baixo para cima ----------------------------------------------------


def test_inativar_setor_com_zona_ativa_falha(db):
    _, setor, _ = _hierarquia(db)

    with pytest.raises(TemFilhosAtivos) as erro:
        inativar_setor(db, setor.id)

    assert erro.value.total == 1
    assert erro.value.nivel_filho == "zona"
    assert buscar_setor_por_id(db, setor.id).ativo is True


def test_inativar_setor_funciona_depois_de_inativar_as_zonas(db):
    _, setor, zona = _hierarquia(db)
    inativar_zona(db, zona.id)

    assert inativar_setor(db, setor.id).ativo is False


def test_inativar_andar_com_setor_ativo_falha(db):
    andar, setor, zona = _hierarquia(db)
    inativar_zona(db, zona.id)  # o setor continua ativo

    with pytest.raises(TemFilhosAtivos) as erro:
        inativar_andar(db, andar.id)

    assert erro.value.nivel_filho == "setor"
    assert buscar_andar_por_id(db, andar.id).ativo is True


def test_inativar_andar_funciona_depois_de_inativar_os_setores(db):
    andar, setor, zona = _hierarquia(db)
    inativar_zona(db, zona.id)
    inativar_setor(db, setor.id)

    assert inativar_andar(db, andar.id).ativo is False


def test_inativar_nao_cascateia_para_os_filhos(db):
    """O bloqueio existe justamente porque nada é inativado por tabela."""
    _, setor, zona = _hierarquia(db)

    with pytest.raises(TemFilhosAtivos):
        inativar_setor(db, setor.id)

    assert buscar_zona_por_id(db, zona.id).ativo is True


# --- zona referenciada -----------------------------------------------------------------


def test_inativar_zona_sem_referencia_funciona(db):
    _, _, zona = _hierarquia(db)

    assert inativar_zona(db, zona.id).ativo is False


def test_inativar_zona_referenciada_por_equipamento_falha(db):
    _, _, zona = _hierarquia(db)
    _equipamento(db, ultima_zona_id=zona.id)

    with pytest.raises(ZonaEmUso) as erro:
        inativar_zona(db, zona.id)

    assert "equipamentos" in erro.value.referenciada_em
    assert buscar_zona_por_id(db, zona.id).ativo is True


def test_inativar_zona_referenciada_por_equipamento_inativo_ainda_falha(db):
    """O critério é 'qualquer referência', mesmo de um registro inativo/antigo."""
    _, _, zona = _hierarquia(db)
    _equipamento(db, ultima_zona_id=zona.id, ativo=False)

    with pytest.raises(ZonaEmUso):
        inativar_zona(db, zona.id)


@pytest.mark.parametrize("lado", ["zona_a", "zona_b"])
def test_inativar_zona_referenciada_por_portal_falha(db, lado):
    _, setor, zona = _hierarquia(db)
    outra = criar_zona(db, setor_id=setor.id, nome="Leito 02")
    if lado == "zona_a":
        _portal(db, zona.id, outra.id)
    else:
        _portal(db, outra.id, zona.id)

    with pytest.raises(ZonaEmUso) as erro:
        inativar_zona(db, zona.id)

    assert "portais" in erro.value.referenciada_em


def test_inativar_zona_referenciada_por_antena_falha(db):
    _, _, zona = _hierarquia(db)
    _antena(db, zona.id)

    with pytest.raises(ZonaEmUso) as erro:
        inativar_zona(db, zona.id)

    assert "antenas" in erro.value.referenciada_em


@pytest.mark.parametrize("papel", ["origem", "destino"])
def test_inativar_zona_referenciada_por_historico_antigo_falha(db, papel):
    _, setor, zona = _hierarquia(db)
    outra = criar_zona(db, setor_id=setor.id, nome="Leito 02")
    if papel == "origem":
        _historico(db, zona_origem_id=zona.id, zona_destino_id=outra.id)
    else:
        _historico(db, zona_origem_id=outra.id, zona_destino_id=zona.id)

    with pytest.raises(ZonaEmUso) as erro:
        inativar_zona(db, zona.id)

    assert "historico_movimentacoes" in erro.value.referenciada_em


def test_inativar_zona_confere_as_referencias_em_ordem(db):
    """Com equipamento E portal apontando, o erro nomeia a PRIMEIRA da ordem."""
    _, setor, zona = _hierarquia(db)
    outra = criar_zona(db, setor_id=setor.id, nome="Leito 02")
    _portal(db, zona.id, outra.id)
    _equipamento(db, ultima_zona_id=zona.id)

    with pytest.raises(ZonaEmUso) as erro:
        inativar_zona(db, zona.id)

    assert "equipamentos" in erro.value.referenciada_em


def test_zona_referenciada_so_bloqueia_a_propria_zona(db):
    _, setor, zona = _hierarquia(db)
    livre = criar_zona(db, setor_id=setor.id, nome="Leito 02")
    _equipamento(db, ultima_zona_id=zona.id)

    assert inativar_zona(db, livre.id).ativo is False


# --- idempotência e não encontrado ----------------------------------------------------


def test_inativar_e_reativar_sao_idempotentes_nos_tres_niveis(db):
    andar, setor, zona = _hierarquia(db)

    # baixo para cima, cada uma duas vezes
    assert inativar_zona(db, zona.id).ativo is False
    assert inativar_zona(db, zona.id).ativo is False
    assert inativar_setor(db, setor.id).ativo is False
    assert inativar_setor(db, setor.id).ativo is False
    assert inativar_andar(db, andar.id).ativo is False
    assert inativar_andar(db, andar.id).ativo is False

    assert reativar_andar(db, andar.id).ativo is True
    assert reativar_andar(db, andar.id).ativo is True
    assert reativar_setor(db, setor.id).ativo is True
    assert reativar_setor(db, setor.id).ativo is True
    assert reativar_zona(db, zona.id).ativo is True
    assert reativar_zona(db, zona.id).ativo is True


def test_inativar_nunca_apaga_a_linha(db):
    _, _, zona = _hierarquia(db)

    inativar_zona(db, zona.id)

    assert buscar_zona_por_id(db, zona.id).ativo is False


def test_buscar_inexistente_levanta_erro_de_dominio(db):
    with pytest.raises(AndarNaoEncontrado):
        buscar_andar_por_id(db, 999_999)
    with pytest.raises(SetorNaoEncontrado):
        buscar_setor_por_id(db, 999_999)
    with pytest.raises(ZonaNaoEncontrada):
        buscar_zona_por_id(db, 999_999)


def test_inativar_e_reativar_inexistente_levantam_erro_de_dominio(db):
    for funcao, erro in (
        (inativar_andar, AndarNaoEncontrado),
        (reativar_andar, AndarNaoEncontrado),
        (inativar_setor, SetorNaoEncontrado),
        (reativar_setor, SetorNaoEncontrado),
        (inativar_zona, ZonaNaoEncontrada),
        (reativar_zona, ZonaNaoEncontrada),
    ):
        with pytest.raises(erro):
            funcao(db, 999_999)


# --- atualizar (PATCH parcial) -----------------------------------------------------------


def test_atualizar_nome_descricao_e_referencia_planta(db):
    andar, setor, zona = _hierarquia(db)

    andar = atualizar_andar(
        db,
        andar.id,
        nome="Quarto Andar",
        descricao="nova",
        descricao_informada=True,
        referencia_planta="P-4",
        referencia_planta_informada=True,
    )
    setor = atualizar_setor(db, setor.id, nome="Ala Leste")
    zona = atualizar_zona(db, zona.id, nome="Leito 99")

    assert (andar.nome, andar.nome_normalizado) == ("Quarto Andar", "quarto andar")
    assert (andar.descricao, andar.referencia_planta) == ("nova", "P-4")
    assert setor.nome_normalizado == "ala leste"
    assert zona.nome_normalizado == "leito 99"


def test_atualizar_sem_informar_campos_preserva_os_atuais(db):
    andar = criar_andar(db, nome="4º Andar", descricao="orig", referencia_planta="P-4")

    atualizado = atualizar_andar(db, andar.id, nome="Quarto Andar")

    assert atualizado.descricao == "orig"
    assert atualizado.referencia_planta == "P-4"


def test_atualizar_informando_null_limpa_o_campo(db):
    andar = criar_andar(db, nome="4º Andar", descricao="orig", referencia_planta="P-4")

    atualizado = atualizar_andar(
        db,
        andar.id,
        descricao=None,
        descricao_informada=True,
        referencia_planta=None,
        referencia_planta_informada=True,
    )

    assert atualizado.descricao is None
    assert atualizado.referencia_planta is None


def test_atualizar_para_nome_ja_usado_no_escopo_falha(db):
    andar = criar_andar(db, nome="4º Andar")
    criar_setor(db, andar_id=andar.id, nome="Ala Norte")
    outro = criar_setor(db, andar_id=andar.id, nome="Ala Sul")

    with pytest.raises(NomeDuplicado) as erro:
        atualizar_setor(db, outro.id, nome="ALA NORTE")

    assert erro.value.nivel == "setor"


def test_atualizar_para_nome_igual_ao_de_outro_escopo_funciona(db):
    andar_3 = criar_andar(db, nome="3º Andar")
    andar_4 = criar_andar(db, nome="4º Andar")
    criar_setor(db, andar_id=andar_3.id, nome="Enfermaria")
    setor_4 = criar_setor(db, andar_id=andar_4.id, nome="UTI")

    assert atualizar_setor(db, setor_4.id, nome="Enfermaria").nome == "Enfermaria"


def test_atualizar_sem_informar_observacoes_preserva_o_valor(db):
    """Um PATCH que só troca outros campos não pode apagar `observacoes`."""
    _, _, zona = _hierarquia(db)
    zona.observacoes = "zona morta perto da janela"
    db.commit()

    atualizar_zona(db, zona.id, nome="Leito 42", descricao="x", descricao_informada=True)

    assert buscar_zona_por_id(db, zona.id).observacoes == "zona morta perto da janela"


def test_atualizar_inexistente_levanta_erro_de_dominio(db):
    with pytest.raises(AndarNaoEncontrado):
        atualizar_andar(db, 999_999, nome="X")


# --- listar -----------------------------------------------------------------------------


def test_listar_andares_paginado_calcula_total_e_pages(db):
    for indice in range(5):
        criar_andar(db, nome=f"Andar {indice}")

    pagina = listar_andares(db, page=1, size=2)

    assert (pagina.total, pagina.pages, len(pagina.items)) == (5, 3, 2)


def test_listar_esconde_inativos_por_padrao_nos_tres_niveis(db):
    andar, setor, zona = _hierarquia(db)
    outra_zona = criar_zona(db, setor_id=setor.id, nome="Leito 02")
    inativar_zona(db, outra_zona.id)

    assert [z.id for z in listar_zonas(db).items] == [zona.id]
    assert listar_zonas(db, incluir_inativos=True).total == 2

    inativar_zona(db, zona.id)
    inativar_setor(db, setor.id)
    assert listar_setores(db).total == 0
    assert listar_setores(db, incluir_inativos=True).total == 1

    inativar_andar(db, andar.id)
    assert listar_andares(db).total == 0
    assert listar_andares(db, incluir_inativos=True).total == 1


def test_listar_setores_filtra_por_andar_e_zonas_por_setor(db):
    andar_a = criar_andar(db, nome="3º Andar")
    andar_b = criar_andar(db, nome="4º Andar")
    setor_a = criar_setor(db, andar_id=andar_a.id, nome="Enfermaria")
    criar_setor(db, andar_id=andar_b.id, nome="UTI")
    criar_zona(db, setor_id=setor_a.id, nome="Leito 01")
    setor_b2 = criar_setor(db, andar_id=andar_b.id, nome="Ala Sul")
    criar_zona(db, setor_id=setor_b2.id, nome="Leito 01")

    assert [s.andar_id for s in listar_setores(db, andar_id=andar_a.id).items] == [andar_a.id]
    assert listar_setores(db, andar_id=andar_b.id).total == 2
    assert [z.setor_id for z in listar_zonas(db, setor_id=setor_a.id).items] == [setor_a.id]


def test_listar_ordem_entre_paginas_e_estavel_com_nomes_repetidos_entre_escopos(db):
    """
    `nome_normalizado` só é único no escopo, então uma listagem que cruza
    escopos tem empates; `_paginar` desempata por `id`. Este teste confere que
    três 'Enfermaria' de andares diferentes não se repetem nem somem entre
    páginas. LIMITE: em tabela pequena o Postgres tende a devolver empates na
    ordem de inserção, então este teste NÃO falharia se o desempate fosse
    removido (verificado por mutação) — o desempate é garantia do código, não
    deste teste.
    """
    for indice in range(3):
        andar = criar_andar(db, nome=f"Andar {indice}")
        criar_setor(db, andar_id=andar.id, nome="Enfermaria")

    vistos = []
    for pagina in (1, 2, 3):
        vistos += [s.id for s in listar_setores(db, page=pagina, size=1).items]

    assert len(vistos) == len(set(vistos)) == 3


# --- árvore ----------------------------------------------------------------------------


def _popular_duas_alas(db):
    andar = criar_andar(db, nome="4º Andar")
    norte = criar_setor(db, andar_id=andar.id, nome="Ala Norte")
    sul = criar_setor(db, andar_id=andar.id, nome="Ala Sul")
    z1 = criar_zona(db, setor_id=norte.id, nome="Corredor")
    z2 = criar_zona(db, setor_id=norte.id, nome="Leito 01")
    z3 = criar_zona(db, setor_id=sul.id, nome="Corredor")
    return andar, norte, sul, z1, z2, z3


def test_arvore_completa_monta_a_hierarquia_certa(db):
    andar, norte, sul, z1, z2, z3 = _popular_duas_alas(db)
    outro = criar_andar(db, nome="5º Andar")

    arvore = arvore_completa(db)

    assert [a.id for a in arvore] == [andar.id, outro.id]
    quarto = arvore[0]
    assert [s.id for s in quarto.setores] == [norte.id, sul.id]
    assert [z.id for z in quarto.setores[0].zonas] == [z1.id, z2.id]
    assert [z.id for z in quarto.setores[1].zonas] == [z3.id]
    assert arvore[1].setores == []
    # cada nó carrega o id do pai
    assert all(s.andar_id == andar.id for s in quarto.setores)
    assert quarto.setores[0].zonas[0].setor_id == norte.id


def test_arvore_esconde_inativos_por_padrao_e_mostra_com_a_opcao(db):
    andar, norte, sul, z1, z2, z3 = _popular_duas_alas(db)
    inativar_zona(db, z2.id)
    inativar_zona(db, z3.id)
    inativar_setor(db, sul.id)

    padrao = arvore_completa(db)[0]
    assert [s.id for s in padrao.setores] == [norte.id]
    assert [z.id for z in padrao.setores[0].zonas] == [z1.id]

    completa = arvore_completa(db, incluir_inativos=True)[0]
    assert [s.id for s in completa.setores] == [norte.id, sul.id]
    assert [(z.id, z.ativo) for z in completa.setores[0].zonas] == [(z1.id, True), (z2.id, False)]
    assert completa.setores[1].ativo is False


def test_arvore_esconde_andar_inativo_por_padrao(db):
    andar, setor, zona = _hierarquia(db)
    inativar_zona(db, zona.id)
    inativar_setor(db, setor.id)
    inativar_andar(db, andar.id)

    assert arvore_completa(db) == []
    assert len(arvore_completa(db, incluir_inativos=True)) == 1


def test_arvore_do_andar_devolve_so_aquele_andar(db):
    andar, norte, sul, *_ = _popular_duas_alas(db)
    criar_andar(db, nome="5º Andar")

    no = arvore_do_andar(db, andar.id)

    assert no.id == andar.id
    assert [s.id for s in no.setores] == [norte.id, sul.id]


def test_arvore_do_andar_inexistente_levanta_erro_de_dominio(db):
    with pytest.raises(AndarNaoEncontrado):
        arvore_do_andar(db, 999_999)


def test_arvore_do_andar_inativo_e_devolvida_quando_pedida_por_id(db):
    andar, setor, zona = _hierarquia(db)
    inativar_zona(db, zona.id)
    inativar_setor(db, setor.id)
    inativar_andar(db, andar.id)

    assert arvore_do_andar(db, andar.id).setores == []
    assert len(arvore_do_andar(db, andar.id, incluir_inativos=True).setores) == 1


def test_montar_arvore_nao_suja_a_sessao(db):
    """
    Regressão da armadilha real: carregar `andar.setores` e reatribuir a lista
    filtrada marca os objetos como sujos, e um autoflush seguinte tenta zerar
    `andar_id`/`setor_id` (NOT NULL) — IntegrityError numa operação que era só
    leitura. Esta sessão tem autoflush LIGADO (o padrão do SQLAlchemy), que é
    o que faria a armadilha disparar.
    """
    andar, norte, sul, z1, z2, z3 = _popular_duas_alas(db)
    inativar_zona(db, z3.id)
    inativar_setor(db, sul.id)  # há inativos para FILTRAR — é o que dispara a armadilha

    arvore_completa(db)
    arvore_do_andar(db, andar.id)
    arvore_completa(db, incluir_inativos=True)

    assert not db.dirty and not db.new and not db.deleted

    # Uma escrita comum logo depois tem que funcionar (o autoflush dela varreria
    # qualquer objeto sujo), e as FKs dos objetos carregados seguem intactas.
    novo = criar_setor(db, andar_id=andar.id, nome="Ala Leste")
    assert novo.id is not None
    assert buscar_setor_por_id(db, norte.id).andar_id == andar.id
    assert buscar_zona_por_id(db, z1.id).setor_id == norte.id
    assert db.scalar(select(Setor).where(Setor.id == sul.id)).andar_id == andar.id
    assert db.scalar(select(Andar).where(Andar.id == andar.id)) is not None


# --- observacoes (zona morta) só na zona ------------------------------------------------


def test_criar_zona_aceita_observacoes(db):
    _, setor, _ = _hierarquia(db)

    zona = criar_zona(db, setor_id=setor.id, nome="Leito 02", observacoes="zona morta perto da janela")

    assert zona.observacoes == "zona morta perto da janela"


def test_criar_zona_sem_observacoes_deixa_nulo(db):
    _, _, zona = _hierarquia(db)

    assert zona.observacoes is None


def test_atualizar_zona_informando_observacoes_grava(db):
    _, _, zona = _hierarquia(db)

    atualizada = atualizar_zona(
        db, zona.id, observacoes="sem sinal atrás do armário", observacoes_informada=True
    )

    assert atualizada.observacoes == "sem sinal atrás do armário"
    # os outros campos não são afetados por informar só as observações
    assert atualizada.nome == "Leito 01"


def test_atualizar_zona_informando_null_limpa_observacoes(db):
    _, setor, _ = _hierarquia(db)
    zona = criar_zona(db, setor_id=setor.id, nome="Leito 02", observacoes="zona morta")

    atualizada = atualizar_zona(db, zona.id, observacoes=None, observacoes_informada=True)

    assert atualizada.observacoes is None


def test_atualizar_zona_observacoes_independe_de_descricao(db):
    _, setor, _ = _hierarquia(db)
    zona = criar_zona(
        db, setor_id=setor.id, nome="Leito 02", descricao="desc", observacoes="zona morta"
    )

    atualizada = atualizar_zona(db, zona.id, descricao="nova", descricao_informada=True)

    assert (atualizada.descricao, atualizada.observacoes) == ("nova", "zona morta")


def test_arvore_carrega_observacoes_da_zona(db):
    _, setor, _ = _hierarquia(db)
    criar_zona(db, setor_id=setor.id, nome="Leito 02", observacoes="zona morta")

    zonas = {z.nome: z for z in arvore_completa(db)[0].setores[0].zonas}

    assert zonas["Leito 02"].observacoes == "zona morta"
    assert zonas["Leito 01"].observacoes is None


# --- reativação de cima para baixo (PaiInativo) --------------------------------------------


def test_reativar_zona_com_setor_inativo_falha(db):
    _, setor, zona = _hierarquia(db)
    inativar_zona(db, zona.id)
    inativar_setor(db, setor.id)

    with pytest.raises(PaiInativo) as erro:
        reativar_zona(db, zona.id)

    assert (erro.value.nivel, erro.value.nivel_pai, erro.value.pai_id) == ("zona", "setor", setor.id)
    assert buscar_zona_por_id(db, zona.id).ativo is False


def test_reativar_zona_com_setor_ativo_funciona(db):
    _, _, zona = _hierarquia(db)
    inativar_zona(db, zona.id)

    assert reativar_zona(db, zona.id).ativo is True


def test_reativar_setor_com_andar_inativo_falha(db):
    andar, setor, zona = _hierarquia(db)
    inativar_zona(db, zona.id)
    inativar_setor(db, setor.id)
    inativar_andar(db, andar.id)

    with pytest.raises(PaiInativo) as erro:
        reativar_setor(db, setor.id)

    assert (erro.value.nivel, erro.value.nivel_pai, erro.value.pai_id) == ("setor", "andar", andar.id)
    assert buscar_setor_por_id(db, setor.id).ativo is False


def test_reativar_setor_com_andar_ativo_funciona(db):
    _, setor, zona = _hierarquia(db)
    inativar_zona(db, zona.id)
    inativar_setor(db, setor.id)

    assert reativar_setor(db, setor.id).ativo is True


def test_reativar_andar_nao_depende_de_ninguem(db):
    andar, setor, zona = _hierarquia(db)
    inativar_zona(db, zona.id)
    inativar_setor(db, setor.id)
    inativar_andar(db, andar.id)

    assert reativar_andar(db, andar.id).ativo is True


def test_reativar_cadeia_inteira_so_funciona_de_cima_para_baixo(db):
    andar, setor, zona = _hierarquia(db)
    inativar_zona(db, zona.id)
    inativar_setor(db, setor.id)
    inativar_andar(db, andar.id)

    # de baixo para cima: bloqueia no primeiro passo
    with pytest.raises(PaiInativo):
        reativar_zona(db, zona.id)
    with pytest.raises(PaiInativo):
        reativar_setor(db, setor.id)

    # de cima para baixo: tudo funciona, e a árvore padrão volta a mostrar a zona
    reativar_andar(db, andar.id)
    reativar_setor(db, setor.id)
    reativar_zona(db, zona.id)
    (no_andar,) = arvore_completa(db)
    assert [z.id for z in no_andar.setores[0].zonas] == [zona.id]


def test_reativar_filho_ja_ativo_e_idempotente_mesmo_com_pai_inativo(db):
    """
    Via serviço não se chega a esse estado (a guarda existe justamente para
    impedi-lo), mas um banco com dado antigo pode tê-lo. Reativar quem já está
    ativo continua sendo um no-op, não um 409: o estado do PRÓPRIO filho já é o
    pedido, e a inconsistência com o pai não é culpa desta chamada.
    """
    _, setor, zona = _hierarquia(db)
    setor.ativo = False  # construído direto no banco, de propósito
    db.commit()

    assert reativar_zona(db, zona.id).ativo is True


# --- hierarquia imutável: o serviço nem aceita reparentar -------------------------------------


def test_atualizar_setor_e_zona_nao_aceitam_id_do_pai():
    import inspect

    assert "andar_id" not in inspect.signature(atualizar_setor).parameters
    assert "setor_id" not in inspect.signature(atualizar_zona).parameters
