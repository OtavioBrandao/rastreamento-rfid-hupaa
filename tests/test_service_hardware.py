"""
Testes da camada de serviço da ISS-012 (leitores, antenas, portais), contra
Postgres de verdade. Rodam sem subir a API; o contrato HTTP está em
`tests/test_api_hardware.py` e a validação de `parametros_ingestao` em
`tests/test_schemas_hardware.py`.
"""

from __future__ import annotations

import inspect
import itertools
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from api.service_hardware import (
    AntenaNaoEncontrada,
    IdentificadorSerialDuplicado,
    LeitorInvalido,
    LeitorNaoEncontrado,
    PortaJaUtilizada,
    PortalInvalido,
    PortalNaoEncontrado,
    ReaderIdDuplicado,
    ZonaInvalidaParaAntena,
    ZonaInvalidaParaPortal,
    ZonasDoPortalIguais,
    atualizar_antena,
    atualizar_leitor,
    atualizar_portal,
    buscar_antena_por_id,
    buscar_leitor_por_id,
    buscar_portal_por_id,
    criar_antena,
    criar_leitor,
    criar_portal,
    inativar_antena,
    inativar_leitor,
    inativar_portal,
    listar_antenas,
    listar_leitores,
    listar_portais,
    reativar_antena,
    reativar_leitor,
    reativar_portal,
)
from api.service_localizacao import (
    ZonaEmUso,
    criar_andar,
    criar_setor,
    criar_zona,
    inativar_zona,
)
from db.models import Antena, Leitor, LeituraBruta, Passagem

_N = itertools.count(1)


# --- helpers ------------------------------------------------------------------------


def _zonas(db, quantas=2):
    andar = criar_andar(db, nome="4º Andar")
    setor = criar_setor(db, andar_id=andar.id, nome="Ala Norte")
    return [criar_zona(db, setor_id=setor.id, nome=f"Zona {i}") for i in range(quantas)]


def _leitor(db, **extra):
    n = next(_N)
    dados = {
        "reader_id": f"reader-{n:03d}",
        "fabricante": "Identix",
        "modelo": "EZ700",
        "identificador_serial": f"SN-{n:04d}",
    }
    dados.update(extra)
    return criar_leitor(db, **dados)


def _portal(db, zonas, nome="Portal 01"):
    return criar_portal(db, nome=nome, zona_a_id=zonas[0].id, zona_b_id=zonas[1].id)


def _antena(db, leitor, zona, porta=1, funcao="entrada", portal=None):
    return criar_antena(
        db,
        leitor_id=leitor.id,
        porta_numero=porta,
        zona_associada_id=zona.id,
        funcao=funcao,
        portal_id=portal.id if portal else None,
    )


# =================================== leitores ===================================


def test_criar_leitor_preenche_defaults_de_cadastro_e_de_conectividade(db):
    leitor = criar_leitor(
        db,
        reader_id="  reader-01 ",
        fabricante=" Identix ",
        modelo="EZ700",
        identificador_serial="SN-0001",
        endereco_rede="192.168.0.10",
    )

    assert leitor.reader_id == "reader-01"  # strip
    assert leitor.fabricante == "Identix"
    assert leitor.ativo is True
    # conectividade ao vivo é da ingestão: o cadastro só herda os defaults do banco
    assert leitor.status == "offline"
    assert leitor.ultimo_heartbeat_em is None


def test_leitor_sem_parametros_de_ingestao_grava_sql_null_e_nao_json_null(db):
    leitor = _leitor(db)

    bruto = db.execute(
        text("SELECT parametros_ingestao IS NULL FROM leitores WHERE id = :id"), {"id": leitor.id}
    ).scalar_one()

    assert bruto is True


def test_reader_id_duplicado_falha(db):
    _leitor(db, reader_id="reader-01")

    with pytest.raises(ReaderIdDuplicado):
        _leitor(db, reader_id="reader-01")


def test_reader_id_e_sensivel_a_caixa(db):
    """`reader_id` é um segmento de tópico MQTT (case-sensitive): UNIQUE exato, sem normalização."""
    _leitor(db, reader_id="reader-01")

    assert _leitor(db, reader_id="READER-01").id is not None


def test_identificador_serial_duplicado_continua_falhando(db):
    _leitor(db, identificador_serial="SN-0001")

    with pytest.raises(IdentificadorSerialDuplicado):
        _leitor(db, identificador_serial="SN-0001")


def test_reader_id_e_identificador_serial_sao_campos_independentes(db):
    """Podem coincidir (no mesmo leitor ou cruzados entre leitores) sem colidir."""
    igual = _leitor(db, reader_id="EZ-0001", identificador_serial="EZ-0001")
    a = _leitor(db, reader_id="reader-a", identificador_serial="SN-A")
    b = _leitor(db, reader_id="SN-A", identificador_serial="reader-a")  # cruzado

    assert (igual.reader_id, igual.identificador_serial) == ("EZ-0001", "EZ-0001")
    assert (a.id, b.id) != (None, None)


def test_sessao_continua_utilizavel_depois_de_duplicidade(db):
    _leitor(db, reader_id="reader-01")

    with pytest.raises(ReaderIdDuplicado):
        _leitor(db, reader_id="reader-01")

    assert _leitor(db, reader_id="reader-02").id is not None


def test_buscar_leitor_inexistente_levanta_erro_de_dominio(db):
    with pytest.raises(LeitorNaoEncontrado):
        buscar_leitor_por_id(db, 999_999)


def test_atualizar_leitor_so_altera_o_que_foi_informado(db):
    leitor = _leitor(db, endereco_rede="10.0.0.1")

    atualizado = atualizar_leitor(db, leitor.id, {"modelo": "EZ800"})

    assert atualizado.modelo == "EZ800"
    assert atualizado.fabricante == "Identix"
    assert atualizado.endereco_rede == "10.0.0.1"
    assert atualizado.reader_id == leitor.reader_id


def test_atualizar_leitor_todos_os_campos_editaveis(db):
    leitor = _leitor(db)

    atualizado = atualizar_leitor(
        db,
        leitor.id,
        {
            "reader_id": "reader-novo",
            "fabricante": "Zebra",
            "modelo": "FX9600",
            "identificador_serial": "SN-NOVO",
            "endereco_rede": "10.0.0.9",
            "parametros_ingestao": {"adapter": "ez700", "qos": 1},
        },
    )

    assert (atualizado.reader_id, atualizado.fabricante, atualizado.modelo) == (
        "reader-novo",
        "Zebra",
        "FX9600",
    )
    assert atualizado.identificador_serial == "SN-NOVO"
    assert atualizado.parametros_ingestao == {"adapter": "ez700", "qos": 1}


def test_atualizar_leitor_com_none_limpa_os_campos_anulaveis(db):
    leitor = _leitor(db, endereco_rede="10.0.0.1", parametros_ingestao={"adapter": "ez700"})

    atualizado = atualizar_leitor(
        db, leitor.id, {"endereco_rede": None, "parametros_ingestao": None}
    )

    assert atualizado.endereco_rede is None
    assert atualizado.parametros_ingestao is None
    nulo = db.execute(
        text("SELECT parametros_ingestao IS NULL FROM leitores WHERE id = :id"), {"id": leitor.id}
    ).scalar_one()
    assert nulo is True


def test_atualizar_leitor_para_reader_id_ja_usado_falha(db):
    _leitor(db, reader_id="reader-01")
    outro = _leitor(db, reader_id="reader-02")

    with pytest.raises(ReaderIdDuplicado):
        atualizar_leitor(db, outro.id, {"reader_id": "reader-01"})


def test_atualizar_leitor_para_serial_ja_usado_falha(db):
    _leitor(db, identificador_serial="SN-A")
    outro = _leitor(db, identificador_serial="SN-B")

    with pytest.raises(IdentificadorSerialDuplicado):
        atualizar_leitor(db, outro.id, {"identificador_serial": "SN-A"})


def test_atualizar_leitor_recusa_campo_de_conectividade(db):
    """`status`/`ultimo_heartbeat_em` são da ingestão: o CRUD nunca os escreve."""
    leitor = _leitor(db)

    for campo in ("status", "ultimo_heartbeat_em", "ativo", "id"):
        with pytest.raises(ValueError, match="não editável"):
            atualizar_leitor(db, leitor.id, {campo: "x"})

    assert buscar_leitor_por_id(db, leitor.id).status == "offline"


def test_atualizar_leitor_com_none_em_coluna_not_null_falha_sem_sujar_a_sessao(db):
    leitor = _leitor(db)

    with pytest.raises(ValueError, match="não pode ser None"):
        atualizar_leitor(db, leitor.id, {"modelo": "EZ800", "fabricante": None})

    # validou ANTES de mutar: nem `modelo` (válido, no mesmo PATCH) ficou pendente
    assert not db.dirty
    assert buscar_leitor_por_id(db, leitor.id).modelo == "EZ700"


def test_atualizar_leitor_inexistente_levanta_erro_de_dominio(db):
    with pytest.raises(LeitorNaoEncontrado):
        atualizar_leitor(db, 999_999, {"modelo": "X"})


def test_listar_leitores_pagina_e_esconde_inativos(db):
    leitores = [_leitor(db) for _ in range(5)]
    inativar_leitor(db, leitores[0].id)

    pagina = listar_leitores(db, page=1, size=2)
    assert (pagina.total, pagina.pages, len(pagina.items)) == (4, 2, 2)
    assert listar_leitores(db, incluir_inativos=True).total == 5


def test_inativar_e_reativar_leitor_sao_idempotentes_e_nao_apagam(db):
    leitor = _leitor(db)

    assert inativar_leitor(db, leitor.id).ativo is False
    assert inativar_leitor(db, leitor.id).ativo is False
    assert buscar_leitor_por_id(db, leitor.id).ativo is False  # a linha continua lá
    assert reativar_leitor(db, leitor.id).ativo is True
    assert reativar_leitor(db, leitor.id).ativo is True


def test_inativar_leitor_nao_cascateia_para_as_antenas(db):
    zona, _ = _zonas(db)
    leitor = _leitor(db)
    antena = _antena(db, leitor, zona)

    inativar_leitor(db, leitor.id)

    assert buscar_antena_por_id(db, antena.id).ativo is True


def test_leitor_inexistente_em_inativar_e_reativar(db):
    with pytest.raises(LeitorNaoEncontrado):
        inativar_leitor(db, 999_999)
    with pytest.raises(LeitorNaoEncontrado):
        reativar_leitor(db, 999_999)


# =================================== portais ===================================


def test_criar_portal(db):
    z1, z2 = _zonas(db)

    portal = criar_portal(
        db, nome=" Portal Norte ", zona_a_id=z1.id, zona_b_id=z2.id, localizacao_fisica="Corredor"
    )

    assert (portal.nome, portal.ativo, portal.localizacao_fisica) == ("Portal Norte", True, "Corredor")
    assert (portal.zona_a_id, portal.zona_b_id) == (z1.id, z2.id)


@pytest.mark.parametrize("lado", ["zona_a_id", "zona_b_id"])
def test_criar_portal_com_zona_inexistente_falha(db, lado):
    z1, z2 = _zonas(db)
    ids = {"zona_a_id": z1.id, "zona_b_id": z2.id, lado: 999_999}

    with pytest.raises(ZonaInvalidaParaPortal) as erro:
        criar_portal(db, nome="P", **ids)

    assert erro.value.lado == lado and "não existe" in erro.value.motivo


@pytest.mark.parametrize("lado", ["zona_a_id", "zona_b_id"])
def test_criar_portal_com_zona_inativa_falha(db, lado):
    z1, z2 = _zonas(db)
    inativar_zona(db, (z1 if lado == "zona_a_id" else z2).id)

    with pytest.raises(ZonaInvalidaParaPortal) as erro:
        criar_portal(db, nome="P", zona_a_id=z1.id, zona_b_id=z2.id)

    assert erro.value.lado == lado and "inativa" in erro.value.motivo


def test_criar_portal_com_as_duas_zonas_iguais_vira_excecao_de_dominio(db):
    """O CHECK `ck_portal_zonas_distintas` do banco é traduzido, não vaza como IntegrityError."""
    z1, _ = _zonas(db)

    with pytest.raises(ZonasDoPortalIguais):
        criar_portal(db, nome="P", zona_a_id=z1.id, zona_b_id=z1.id)

    # a sessão continua utilizável depois do rollback do serviço
    assert db.scalar(select(func.count()).select_from(Antena)) == 0


def test_atualizar_portal_campos_informados(db):
    z1, z2 = _zonas(db, 3)[:2]
    portal = _portal(db, [z1, z2])

    atualizado = atualizar_portal(db, portal.id, {"nome": "Portal Sul", "localizacao_fisica": "Hall"})

    assert (atualizado.nome, atualizado.localizacao_fisica) == ("Portal Sul", "Hall")
    assert (atualizado.zona_a_id, atualizado.zona_b_id) == (z1.id, z2.id)


def test_atualizar_portal_troca_de_zona_e_limpa_localizacao(db):
    z1, z2, z3 = _zonas(db, 3)
    portal = criar_portal(db, nome="P", zona_a_id=z1.id, zona_b_id=z2.id, localizacao_fisica="x")

    atualizado = atualizar_portal(db, portal.id, {"zona_b_id": z3.id, "localizacao_fisica": None})

    assert atualizado.zona_b_id == z3.id
    assert atualizado.localizacao_fisica is None


def test_atualizar_portal_para_zona_inativa_falha_e_nada_muda(db):
    z1, z2, z3 = _zonas(db, 3)
    portal = _portal(db, [z1, z2])
    inativar_zona(db, z3.id)

    with pytest.raises(ZonaInvalidaParaPortal):
        atualizar_portal(db, portal.id, {"nome": "Novo", "zona_b_id": z3.id})

    assert not db.dirty
    atual = buscar_portal_por_id(db, portal.id)
    assert (atual.nome, atual.zona_b_id) == ("Portal 01", z2.id)


def test_atualizar_portal_para_zonas_iguais_vira_excecao_de_dominio(db):
    z1, z2 = _zonas(db)
    portal = _portal(db, [z1, z2])

    with pytest.raises(ZonasDoPortalIguais):
        atualizar_portal(db, portal.id, {"zona_a_id": z2.id})  # a == b (z2)

    assert buscar_portal_por_id(db, portal.id).zona_a_id == z1.id


def test_atualizar_portal_recusa_campo_nao_editavel_e_none_em_not_null(db):
    portal = _portal(db, _zonas(db))

    with pytest.raises(ValueError, match="não editável"):
        atualizar_portal(db, portal.id, {"ativo": False})
    with pytest.raises(ValueError, match="não pode ser None"):
        atualizar_portal(db, portal.id, {"nome": None})


def test_portal_inexistente(db):
    for funcao in (buscar_portal_por_id, inativar_portal, reativar_portal):
        with pytest.raises(PortalNaoEncontrado):
            funcao(db, 999_999)
    with pytest.raises(PortalNaoEncontrado):
        atualizar_portal(db, 999_999, {"nome": "X"})


def test_listar_portais_e_inativar_reativar_idempotente(db):
    z1, z2 = _zonas(db)
    a = _portal(db, [z1, z2], nome="A")
    _portal(db, [z1, z2], nome="B")

    assert inativar_portal(db, a.id).ativo is False
    assert inativar_portal(db, a.id).ativo is False
    assert [p.nome for p in listar_portais(db).items] == ["B"]
    assert listar_portais(db, incluir_inativos=True).total == 2
    assert reativar_portal(db, a.id).ativo is True
    assert reativar_portal(db, a.id).ativo is True


# =================================== antenas ===================================


def test_criar_antena_sem_portal(db):
    zona, _ = _zonas(db)
    leitor = _leitor(db)

    antena = _antena(db, leitor, zona, porta=1, funcao="entrada")

    assert (antena.leitor_id, antena.porta_numero, antena.funcao) == (leitor.id, 1, "entrada")
    assert antena.portal_id is None  # antena pode existir antes de ser instalada num portal
    assert antena.ativo is True


def test_criar_antena_ja_associada_a_um_portal(db):
    zonas = _zonas(db)
    portal = _portal(db, zonas)

    antena = _antena(db, _leitor(db), zonas[0], portal=portal)

    assert antena.portal_id == portal.id


def test_criar_antena_com_leitor_inexistente_falha(db):
    zona, _ = _zonas(db)

    with pytest.raises(LeitorInvalido) as erro:
        criar_antena(db, leitor_id=999_999, porta_numero=1, zona_associada_id=zona.id, funcao="entrada")

    assert "não existe" in erro.value.motivo


def test_criar_antena_com_leitor_inativo_falha(db):
    zona, _ = _zonas(db)
    leitor = _leitor(db)
    inativar_leitor(db, leitor.id)

    with pytest.raises(LeitorInvalido) as erro:
        _antena(db, leitor, zona)

    assert "inativo" in erro.value.motivo


def test_criar_antena_com_zona_inexistente_ou_inativa_falha(db):
    zona, _ = _zonas(db)
    leitor = _leitor(db)

    with pytest.raises(ZonaInvalidaParaAntena) as erro:
        criar_antena(db, leitor_id=leitor.id, porta_numero=1, zona_associada_id=999_999, funcao="entrada")
    assert "não existe" in erro.value.motivo

    inativar_zona(db, zona.id)
    with pytest.raises(ZonaInvalidaParaAntena) as erro:
        _antena(db, leitor, zona)
    assert "inativa" in erro.value.motivo


def test_criar_antena_com_portal_inexistente_ou_inativo_falha(db):
    zonas = _zonas(db)
    leitor = _leitor(db)

    with pytest.raises(PortalInvalido) as erro:
        criar_antena(
            db,
            leitor_id=leitor.id,
            porta_numero=1,
            zona_associada_id=zonas[0].id,
            funcao="entrada",
            portal_id=999_999,
        )
    assert "não existe" in erro.value.motivo

    portal = _portal(db, zonas)
    inativar_portal(db, portal.id)
    with pytest.raises(PortalInvalido) as erro:
        _antena(db, leitor, zonas[0], portal=portal)
    assert "inativo" in erro.value.motivo


def test_porta_repetida_no_mesmo_leitor_falha(db):
    zona, _ = _zonas(db)
    leitor = _leitor(db)
    _antena(db, leitor, zona, porta=1)

    with pytest.raises(PortaJaUtilizada) as erro:
        _antena(db, leitor, zona, porta=1, funcao="saida")

    assert (erro.value.leitor_id, erro.value.porta_numero) == (leitor.id, 1)


def test_mesma_porta_em_leitores_diferentes_e_permitida(db):
    zona, _ = _zonas(db)

    a = _antena(db, _leitor(db), zona, porta=1)
    b = _antena(db, _leitor(db), zona, porta=1)

    assert a.id != b.id


def test_sessao_continua_utilizavel_depois_de_porta_repetida(db):
    zona, _ = _zonas(db)
    leitor = _leitor(db)
    _antena(db, leitor, zona, porta=1)

    with pytest.raises(PortaJaUtilizada):
        _antena(db, leitor, zona, porta=1)

    assert _antena(db, leitor, zona, porta=2).id is not None


def test_antena_inativa_libera_a_porta_para_uma_antena_nova(db):
    """
    `uq_antena_ativa_por_porta_leitor` é um índice único PARCIAL (WHERE ativo), o
    mesmo padrão de `uq_tag_ativa` (ISS-010): só a antena ATIVA ocupa a porta.
    """
    zona, _ = _zonas(db)
    leitor = _leitor(db)
    antiga = _antena(db, leitor, zona, porta=1)
    inativar_antena(db, antiga.id)

    nova = _antena(db, leitor, zona, porta=1, funcao="saida")  # não levanta

    assert nova.id != antiga.id and nova.ativo is True
    # a linha antiga continua existindo (o histórico de leituras a referencia)
    assert buscar_antena_por_id(db, antiga.id).ativo is False
    # e a porta passa a ter 2 linhas: 1 ativa, 1 inativa
    todas = listar_antenas(db, leitor_id=leitor.id, incluir_inativos=True).items
    assert sorted(a.ativo for a in todas) == [False, True]


def test_porta_continua_unica_entre_antenas_ativas(db):
    zona, _ = _zonas(db)
    leitor = _leitor(db)
    _antena(db, leitor, zona, porta=1)

    with pytest.raises(PortaJaUtilizada) as erro:
        _antena(db, leitor, zona, porta=1)

    assert "ATIVA" in str(erro.value)


def test_a_traducao_pega_o_nome_real_do_indice_parcial(db):
    """O erro que o Postgres devolve para o índice tem que ser reconhecido de verdade."""
    zona, _ = _zonas(db)
    leitor = _leitor(db)
    _antena(db, leitor, zona, porta=1)

    with pytest.raises(PortaJaUtilizada) as erro:
        _antena(db, leitor, zona, porta=1)

    causa = erro.value.__cause__
    assert causa.orig.pgcode == "23505"
    assert causa.orig.diag.constraint_name == "uq_antena_ativa_por_porta_leitor"


def test_inativar_a_nova_antena_nao_libera_a_antiga_por_engano(db):
    """Duas linhas na porta 1: a inativa NÃO volta a ativa sozinha."""
    zona, _ = _zonas(db)
    leitor = _leitor(db)
    antiga = _antena(db, leitor, zona, porta=1)
    inativar_antena(db, antiga.id)
    nova = _antena(db, leitor, zona, porta=1)

    inativar_antena(db, nova.id)

    assert buscar_antena_por_id(db, antiga.id).ativo is False
    assert buscar_antena_por_id(db, nova.id).ativo is False


def test_reativar_antena_cuja_porta_foi_tomada_por_outra_ativa_falha(db):
    zona, _ = _zonas(db)
    leitor = _leitor(db)
    antiga = _antena(db, leitor, zona, porta=1)
    inativar_antena(db, antiga.id)
    _antena(db, leitor, zona, porta=1)  # tomou a porta

    with pytest.raises(PortaJaUtilizada) as erro:
        reativar_antena(db, antiga.id)

    assert (erro.value.leitor_id, erro.value.porta_numero) == (leitor.id, 1)
    assert buscar_antena_por_id(db, antiga.id).ativo is False  # nada mudou
    # a sessão continua utilizável depois do rollback do serviço
    assert _antena(db, leitor, zona, porta=2).id is not None


def test_reativar_antena_funciona_quando_a_porta_esta_livre(db):
    zona, _ = _zonas(db)
    leitor = _leitor(db)
    antiga = _antena(db, leitor, zona, porta=1)
    inativar_antena(db, antiga.id)
    nova = _antena(db, leitor, zona, porta=1)

    inativar_antena(db, nova.id)  # libera a porta de novo

    assert reativar_antena(db, antiga.id).ativo is True


def test_atualizar_antena_inativa_para_porta_ocupada_so_falha_ao_reativar(db):
    """A inativa não entra no índice: mover para porta ocupada é permitido; reativar é que colide."""
    zona, _ = _zonas(db)
    leitor = _leitor(db)
    ocupada = _antena(db, leitor, zona, porta=1)
    outra = _antena(db, leitor, zona, porta=2)
    inativar_antena(db, outra.id)

    assert atualizar_antena(db, outra.id, {"porta_numero": 1}).porta_numero == 1  # inativa: ok
    with pytest.raises(PortaJaUtilizada):
        reativar_antena(db, outra.id)
    assert buscar_antena_por_id(db, ocupada.id).ativo is True


def test_atualizar_antena_ativa_para_porta_de_uma_antena_inativa_funciona(db):
    zona, _ = _zonas(db)
    leitor = _leitor(db)
    inativa = _antena(db, leitor, zona, porta=1)
    inativar_antena(db, inativa.id)
    ativa = _antena(db, leitor, zona, porta=2)

    assert atualizar_antena(db, ativa.id, {"porta_numero": 1}).porta_numero == 1


# --- created_at / updated_at ------------------------------------------------------------------------


def test_leitor_antena_e_portal_tem_created_at_e_updated_at(db):
    zonas = _zonas(db)
    leitor = _leitor(db)
    portal = _portal(db, zonas)
    antena = _antena(db, leitor, zonas[0])

    for entidade in (leitor, portal, antena):
        assert entidade.created_at is not None and entidade.updated_at is not None


def test_atualizar_antena_campos_informados(db):
    z1, z2 = _zonas(db)
    leitor = _leitor(db)
    antena = _antena(db, leitor, z1, porta=1, funcao="entrada")

    atualizada = atualizar_antena(
        db, antena.id, {"porta_numero": 2, "zona_associada_id": z2.id, "funcao": "saida"}
    )

    assert (atualizada.porta_numero, atualizada.zona_associada_id, atualizada.funcao) == (2, z2.id, "saida")
    assert atualizada.leitor_id == leitor.id


def test_atualizar_antena_associa_troca_e_desassocia_portal(db):
    zonas = _zonas(db)
    p1 = _portal(db, zonas, nome="P1")
    p2 = _portal(db, zonas, nome="P2")
    antena = _antena(db, _leitor(db), zonas[0], portal=p1)

    assert atualizar_antena(db, antena.id, {"portal_id": p2.id}).portal_id == p2.id
    # portal_id É editável e aceita None: desassociar é uma edição legítima
    assert atualizar_antena(db, antena.id, {"portal_id": None}).portal_id is None
    assert atualizar_antena(db, antena.id, {"portal_id": p1.id}).portal_id == p1.id


def test_atualizar_antena_sem_informar_portal_preserva_o_atual(db):
    zonas = _zonas(db)
    portal = _portal(db, zonas)
    antena = _antena(db, _leitor(db), zonas[0], portal=portal)

    assert atualizar_antena(db, antena.id, {"funcao": "saida"}).portal_id == portal.id


def test_leitor_id_da_antena_nao_e_editavel(db):
    zona, _ = _zonas(db)
    a = _leitor(db)
    b = _leitor(db)
    antena = _antena(db, a, zona)

    with pytest.raises(ValueError, match="leitor_id"):
        atualizar_antena(db, antena.id, {"leitor_id": b.id})

    assert buscar_antena_por_id(db, antena.id).leitor_id == a.id
    assert "leitor_id" not in inspect.signature(atualizar_antena).parameters


def test_atualizar_antena_para_zona_ou_portal_invalidos_falha_e_nada_muda(db):
    z1, z2, z3 = _zonas(db, 3)
    portal = _portal(db, [z1, z2])
    antena = _antena(db, _leitor(db), z1, porta=1)
    inativar_zona(db, z3.id)  # z3 livre: as zonas do portal ficam bloqueadas (ZonaEmUso, ISS-011)

    with pytest.raises(ZonaInvalidaParaAntena):
        atualizar_antena(db, antena.id, {"porta_numero": 3, "zona_associada_id": z3.id})
    inativar_portal(db, portal.id)
    with pytest.raises(PortalInvalido):
        atualizar_antena(db, antena.id, {"porta_numero": 3, "portal_id": portal.id})
    with pytest.raises(PortalInvalido):
        atualizar_antena(db, antena.id, {"portal_id": 999_999})

    assert not db.dirty
    atual = buscar_antena_por_id(db, antena.id)
    assert (atual.porta_numero, atual.zona_associada_id, atual.portal_id) == (1, z1.id, None)


def test_atualizar_antena_para_porta_ja_usada_falha(db):
    zona, _ = _zonas(db)
    leitor = _leitor(db)
    _antena(db, leitor, zona, porta=1)
    outra = _antena(db, leitor, zona, porta=2)

    with pytest.raises(PortaJaUtilizada):
        atualizar_antena(db, outra.id, {"porta_numero": 1})

    assert buscar_antena_por_id(db, outra.id).porta_numero == 2


def test_atualizar_antena_recusa_none_em_not_null_e_campo_inexistente(db):
    zona, _ = _zonas(db)
    antena = _antena(db, _leitor(db), zona)

    with pytest.raises(ValueError, match="não pode ser None"):
        atualizar_antena(db, antena.id, {"funcao": None})
    with pytest.raises(ValueError, match="não editável"):
        atualizar_antena(db, antena.id, {"ativo": False})


def test_antena_inexistente(db):
    for funcao in (buscar_antena_por_id, inativar_antena, reativar_antena):
        with pytest.raises(AntenaNaoEncontrada):
            funcao(db, 999_999)
    with pytest.raises(AntenaNaoEncontrada):
        atualizar_antena(db, 999_999, {"funcao": "saida"})


def test_listar_antenas_filtra_por_leitor_e_por_portal_e_esconde_inativas(db):
    zonas = _zonas(db)
    portal = _portal(db, zonas)
    l1, l2 = _leitor(db), _leitor(db)
    a1 = _antena(db, l1, zonas[0], porta=1, portal=portal)
    _antena(db, l1, zonas[0], porta=2)
    a3 = _antena(db, l2, zonas[1], porta=1, portal=portal)

    assert {a.id for a in listar_antenas(db, leitor_id=l1.id).items} != set()
    assert listar_antenas(db, leitor_id=l1.id).total == 2
    assert {a.id for a in listar_antenas(db, portal_id=portal.id).items} == {a1.id, a3.id}

    inativar_antena(db, a1.id)
    assert {a.id for a in listar_antenas(db, portal_id=portal.id).items} == {a3.id}
    assert listar_antenas(db, portal_id=portal.id, incluir_inativos=True).total == 2


def test_inativar_e_reativar_antena_sao_idempotentes_e_nao_apagam(db):
    zona, _ = _zonas(db)
    antena = _antena(db, _leitor(db), zona)

    assert inativar_antena(db, antena.id).ativo is False
    assert inativar_antena(db, antena.id).ativo is False
    assert buscar_antena_por_id(db, antena.id).ativo is False
    assert reativar_antena(db, antena.id).ativo is True
    assert reativar_antena(db, antena.id).ativo is True


# =========================== as duas topologias obrigatórias ===========================


def test_topologia_1_um_leitor_com_varias_antenas_em_portas_diferentes(db):
    zonas = _zonas(db, 4)
    leitor = _leitor(db)

    antenas = [
        _antena(db, leitor, zonas[i], porta=i + 1, funcao=f)
        for i, f in enumerate(("entrada", "saida", "entrada", "indefinido"))
    ]

    doLeitor = listar_antenas(db, leitor_id=leitor.id).items
    assert [a.porta_numero for a in doLeitor] == [1, 2, 3, 4]  # ordenadas por porta
    assert {a.id for a in doLeitor} == {a.id for a in antenas}
    assert {a.leitor_id for a in doLeitor} == {leitor.id}
    # e as portas continuam únicas POR leitor
    with pytest.raises(PortaJaUtilizada):
        _antena(db, leitor, zonas[0], porta=3)


def test_topologia_2_um_portal_composto_por_antenas_de_leitores_distintos(db):
    """
    O critério central que motivou `Antena.portal_id` (em vez de
    `Leitor.portal_id`): a antena de entrada vem de um leitor e a de saída de
    outro, e ambas pertencem ao MESMO portal.
    """
    zonas = _zonas(db)
    portal = _portal(db, zonas)
    leitor_a, leitor_b = _leitor(db), _leitor(db)

    entrada = _antena(db, leitor_a, zonas[0], porta=1, funcao="entrada", portal=portal)
    saida = _antena(db, leitor_b, zonas[1], porta=1, funcao="saida", portal=portal)  # mesma porta, outro leitor

    do_portal = listar_antenas(db, portal_id=portal.id).items
    assert {a.id for a in do_portal} == {entrada.id, saida.id}
    assert {a.leitor_id for a in do_portal} == {leitor_a.id, leitor_b.id}  # leitores DISTINTOS
    assert len({a.portal_id for a in do_portal}) == 1


def test_topologia_2b_um_leitor_com_antenas_em_portais_diferentes(db):
    zonas = _zonas(db, 3)
    p1 = _portal(db, zonas[:2], nome="P1")
    p2 = criar_portal(db, nome="P2", zona_a_id=zonas[1].id, zona_b_id=zonas[2].id)
    leitor = _leitor(db)

    a1 = _antena(db, leitor, zonas[0], porta=1, portal=p1)
    a2 = _antena(db, leitor, zonas[2], porta=2, portal=p2)

    assert {a.portal_id for a in listar_antenas(db, leitor_id=leitor.id).items} == {p1.id, p2.id}
    assert buscar_antena_por_id(db, a1.id).portal_id != buscar_antena_por_id(db, a2.id).portal_id


def test_leitor_nao_tem_mais_portal_id(db):
    """A associação com portal mora na antena; o leitor não tem mais coluna nem relationship."""
    assert not hasattr(Leitor, "portal_id") and not hasattr(Leitor, "portal")


# ========== inativar NÃO é bloqueado por histórico (diferente de ZonaEmUso, ISS-011) ==========


def _historico(db, antena, portal):
    """Uma leitura bruta e uma passagem que referenciam a antena e o portal."""
    leitura = LeituraBruta(
        event_id=uuid.uuid4(),
        antena_id=antena.id,
        epc="AABBCCDD",
        rssi=Decimal("-55"),
        lido_em=datetime.now(timezone.utc),
    )
    db.add(leitura)
    db.flush()
    db.add(
        Passagem(
            epc="AABBCCDD",
            portal_id=portal.id,
            antena_origem_id=antena.id,
            leitura_origem_id=leitura.id,
            detectada_em=datetime.now(timezone.utc),
        )
    )
    db.commit()


def test_inativar_leitor_antena_e_portal_com_historico_nao_e_bloqueado(db):
    """
    Regra DELIBERADAMENTE diferente da ISS-011: lá, `inativar_zona` é bloqueada
    por QUALQUER referência (ZonaEmUso). Aqui nada bloqueia: "hardware inativo
    permanece referenciado pelo histórico". Inativar é só um toggle de `ativo`.
    """
    zonas = _zonas(db)
    portal = _portal(db, zonas)
    leitor = _leitor(db)
    antena = _antena(db, leitor, zonas[0], portal=portal)
    _historico(db, antena, portal)

    # nenhuma das três levanta — e as três seguem referenciadas pelo histórico
    assert inativar_antena(db, antena.id).ativo is False
    assert inativar_portal(db, portal.id).ativo is False
    assert inativar_leitor(db, leitor.id).ativo is False

    assert buscar_antena_por_id(db, antena.id).ativo is False
    assert db.scalar(select(func.count()).select_from(LeituraBruta)) == 1
    assert db.scalar(select(func.count()).select_from(Passagem)) == 1
    # a linha do histórico ainda resolve o hardware inativo
    passagem = db.scalar(select(Passagem))
    assert passagem.portal_id == portal.id and passagem.antena_origem_id == antena.id


def test_o_contraste_com_a_iss011_zona_referenciada_pelo_hardware_continua_bloqueada(db):
    """A outra metade da regra: quem referencia a zona (portal/antena) a mantém bloqueada."""
    zonas = _zonas(db)
    portal = _portal(db, zonas)
    antena = _antena(db, _leitor(db), zonas[0], portal=portal)
    inativar_antena(db, antena.id)
    inativar_portal(db, portal.id)

    # mesmo com portal e antena INATIVOS, as zonas seguem referenciadas
    with pytest.raises(ZonaEmUso):
        inativar_zona(db, zonas[0].id)
    with pytest.raises(ZonaEmUso):
        inativar_zona(db, zonas[1].id)
