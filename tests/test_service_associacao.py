"""
Testes da camada de serviço da ISS-010 (RF-003), contra Postgres de verdade.

Rodam sem subir a API: o alvo aqui é a regra de negócio. O contrato HTTP
desta issue foi validado por smoke test manual (uvicorn real), não por
suíte automatizada — não há `tests/test_api_associacao.py` de propósito,
os schemas/router só traduzem o que já está coberto aqui. O teste de
concorrência real fica separado, em `tests/test_concorrencia_associacao.py`
— esta fixture `db` (savepoint numa única conexão) não serve pra isso.
"""

from __future__ import annotations

import itertools

import pytest
from sqlalchemy import select

from api.service_associacao import (
    EquipamentoInvalido,
    EquipamentoJaPossuiVinculoAtivo,
    NenhumVinculoAtivo,
    TagJaAssociada,
    TagJaEhAAtiva,
    associar,
    encerrar,
    historico_por_equipamento,
    resolver_epc,
    substituir,
    vinculo_ativo_por_equipamento,
)
from api.service_equipamento import criar as criar_equipamento
from api.service_equipamento import inativar as inativar_equipamento
from api.service_tipos_equipamento import criar as criar_tipo
from db.models import Auditoria, TipoEquipamento

_CONTADOR_IDENTIFICADOR = itertools.count(1)


def _tipo_padrao(db):
    """
    Reaproveita um único tipo_equipamento ("Maca") em vez de criar um novo
    a cada chamada.

    Bug real encontrado no sandbox: um helper que cria um `TipoEquipamento`
    novo a cada `_criar_equipamento()` colide com o UNIQUE de
    `nome_normalizado` (ISS-009) na segunda chamada dentro do MESMO teste
    — e testes deste arquivo precisam de 2+ equipamentos o tempo todo
    (associar duas tags a dois equipamentos, mover uma tag entre dois,
    etc.). Buscar-ou-criar em vez de sempre criar evita a colisão.
    """
    tipo = db.scalar(select(TipoEquipamento).where(TipoEquipamento.nome_normalizado == "maca"))
    if tipo is None:
        tipo = criar_tipo(db, nome="Maca")
    return tipo


def _criar_equipamento(db, identificador: str | None = None, ativo: bool = True):
    tipo = _tipo_padrao(db)
    if identificador is None:
        identificador = f"PAT-{next(_CONTADOR_IDENTIFICADOR):04d}"
    equipamento = criar_equipamento(
        db, nome="Equipamento de teste", tipo_id=tipo.id, identificador_interno=identificador
    )
    if not ativo:
        equipamento = inativar_equipamento(db, equipamento.id)
    return equipamento


# --- associar() -----------------------------------------------------------


def test_associar_cria_vinculo_ativo(db):
    equipamento = _criar_equipamento(db)

    associacao = associar(db, equipamento.id, "abcdef01")

    assert associacao.id is not None
    assert associacao.equipamento_id == equipamento.id
    assert associacao.tag.epc == "ABCDEF01"
    assert associacao.fim is None


def test_associar_normaliza_epc_antes_de_gravar(db):
    equipamento = _criar_equipamento(db)

    associacao = associar(db, equipamento.id, "  abCDef01  ")

    assert associacao.tag.epc == "ABCDEF01"


def test_associar_com_epc_minusculo_e_maiusculo_colide(db):
    """A normalização é a chave real de unicidade: 'abcdef01' e 'ABCDEF01'
    são o MESMO EPC, então a segunda tentativa tem que ser rejeitada."""
    equipamento_a = _criar_equipamento(db)
    equipamento_b = _criar_equipamento(db)
    associar(db, equipamento_a.id, "abcdef01")

    with pytest.raises(TagJaAssociada):
        associar(db, equipamento_b.id, "ABCDEF01")


def test_associar_grava_auditoria_de_vincular_epc(db):
    equipamento = _criar_equipamento(db)

    associacao = associar(db, equipamento.id, "abcdef01")

    auditoria = db.scalar(
        select(Auditoria).where(
            Auditoria.entidade == "associacoes_tag_equipamento",
            Auditoria.entidade_id == associacao.id,
        )
    )
    assert auditoria is not None
    assert auditoria.acao == "vincular_epc"
    assert auditoria.dados_antes is None
    assert auditoria.dados_depois["epc"] == "ABCDEF01"
    assert auditoria.dados_depois["equipamento_id"] == equipamento.id


def test_associar_com_equipamento_inexistente_falha(db):
    with pytest.raises(EquipamentoInvalido):
        associar(db, 999_999, "abcdef01")


def test_associar_com_equipamento_inativo_falha(db):
    equipamento = _criar_equipamento(db, ativo=False)

    with pytest.raises(EquipamentoInvalido):
        associar(db, equipamento.id, "abcdef01")


def test_associar_tag_ja_ativa_em_outro_equipamento_falha(db):
    equipamento_a = _criar_equipamento(db)
    equipamento_b = _criar_equipamento(db)
    associar(db, equipamento_a.id, "abcdef01")

    with pytest.raises(TagJaAssociada):
        associar(db, equipamento_b.id, "abcdef01")

    # Sem efeito colateral: o vínculo do equipamento B continua inexistente.
    assert vinculo_ativo_por_equipamento(db, equipamento_b.id) is None


def test_associar_equipamento_que_ja_tem_vinculo_ativo_falha(db):
    equipamento = _criar_equipamento(db)
    associar(db, equipamento.id, "abcdef01")

    with pytest.raises(EquipamentoJaPossuiVinculoAtivo):
        associar(db, equipamento.id, "11223344")

    # O vínculo original continua sendo o da primeira tag.
    assert vinculo_ativo_por_equipamento(db, equipamento.id).tag.epc == "ABCDEF01"


# --- substituir() -----------------------------------------------------------


def test_substituir_encerra_vinculo_anterior_e_cria_novo(db):
    equipamento = _criar_equipamento(db)
    primeira = associar(db, equipamento.id, "abcdef01")

    segunda = substituir(db, equipamento.id, "11223344")

    assert segunda.id != primeira.id
    assert segunda.tag.epc == "11223344"
    assert segunda.fim is None

    historico = historico_por_equipamento(db, equipamento.id)
    # A linha antiga NÃO foi apagada — continua existindo, com `fim`
    # preenchido. É o ponto central de "histórico, nunca DELETE".
    assert len(historico) == 2
    antiga = next(item for item in historico if item.id == primeira.id)
    assert antiga.fim is not None
    assert antiga.tag.epc == "ABCDEF01"


def test_substituir_grava_desvincular_e_vincular_correlacionados(db):
    equipamento = _criar_equipamento(db)
    anterior = associar(db, equipamento.id, "abcdef01")

    nova = substituir(db, equipamento.id, "11223344")

    def trilha(acao, entidade_id):
        return db.scalar(select(Auditoria).where(
            Auditoria.entidade == "associacoes_tag_equipamento",
            Auditoria.entidade_id == entidade_id, Auditoria.acao == acao,
        ))

    desvinculo = trilha("desvincular_epc", anterior.id)
    vinculo = trilha("vincular_epc", nova.id)
    assert desvinculo is not None and vinculo is not None
    assert (desvinculo.dados_antes["epc"], desvinculo.dados_depois["epc"]) == (
        "ABCDEF01", "ABCDEF01")
    assert desvinculo.dados_antes["fim"] is None and desvinculo.dados_depois["fim"] is not None
    assert vinculo.dados_depois["epc"] == "11223344"
    assert desvinculo.correlation_id == vinculo.correlation_id


def test_substituir_sem_vinculo_ativo_falha(db):
    equipamento = _criar_equipamento(db)

    with pytest.raises(NenhumVinculoAtivo):
        substituir(db, equipamento.id, "abcdef01")


def test_substituir_pedindo_a_mesma_tag_falha(db):
    equipamento = _criar_equipamento(db)
    associar(db, equipamento.id, "abcdef01")

    with pytest.raises(TagJaEhAAtiva):
        substituir(db, equipamento.id, "abcdef01")

    # Sem efeito colateral: continua um único registro no histórico.
    assert len(historico_por_equipamento(db, equipamento.id)) == 1


def test_substituir_por_tag_ativa_em_outro_equipamento_falha(db):
    equipamento_a = _criar_equipamento(db)
    equipamento_b = _criar_equipamento(db)
    associar(db, equipamento_a.id, "abcdef01")
    associar(db, equipamento_b.id, "11223344")

    with pytest.raises(TagJaAssociada):
        substituir(db, equipamento_b.id, "abcdef01")

    # O vínculo de B não foi tocado pela tentativa que falhou.
    assert vinculo_ativo_por_equipamento(db, equipamento_b.id).tag.epc == "11223344"
    assert len(historico_por_equipamento(db, equipamento_b.id)) == 1


def test_substituir_com_equipamento_inexistente_falha(db):
    with pytest.raises(EquipamentoInvalido):
        substituir(db, 999_999, "abcdef01")


def test_substituir_com_equipamento_inativo_falha(db):
    equipamento = _criar_equipamento(db, ativo=False)

    with pytest.raises(EquipamentoInvalido):
        substituir(db, equipamento.id, "abcdef01")


# --- encerrar() -------------------------------------------------------------


def test_encerrar_preserva_a_linha_e_marca_fim(db):
    equipamento = _criar_equipamento(db)
    associacao = associar(db, equipamento.id, "abcdef01")

    encerrada = encerrar(db, equipamento.id)

    assert encerrada.id == associacao.id
    assert encerrada.fim is not None
    # Não apagou: a história continua com exatamente 1 registro.
    assert len(historico_por_equipamento(db, equipamento.id)) == 1
    assert vinculo_ativo_por_equipamento(db, equipamento.id) is None


def test_encerrar_grava_auditoria_de_desvincular_epc(db):
    equipamento = _criar_equipamento(db)
    associacao = associar(db, equipamento.id, "abcdef01")

    encerrar(db, equipamento.id)

    auditoria = db.scalar(
        select(Auditoria).where(
            Auditoria.entidade == "associacoes_tag_equipamento",
            Auditoria.entidade_id == associacao.id,
            Auditoria.acao == "desvincular_epc",
        )
    )
    assert auditoria is not None
    assert auditoria.dados_antes == {"fim": None, "epc": "ABCDEF01"}
    assert auditoria.dados_depois["epc"] == "ABCDEF01"
    assert auditoria.dados_depois["fim"] is not None


def test_encerrar_libera_a_tag_para_outro_equipamento(db):
    equipamento_a = _criar_equipamento(db)
    equipamento_b = _criar_equipamento(db)
    associar(db, equipamento_a.id, "abcdef01")

    encerrar(db, equipamento_a.id)
    associacao_b = associar(db, equipamento_b.id, "abcdef01")

    assert associacao_b.tag.epc == "ABCDEF01"
    assert associacao_b.equipamento_id == equipamento_b.id


def test_encerrar_sem_vinculo_ativo_falha(db):
    equipamento = _criar_equipamento(db)

    with pytest.raises(NenhumVinculoAtivo):
        encerrar(db, equipamento.id)


# --- resolver_epc() ----------------------------------------------------------


def test_resolver_epc_retorna_none_para_epc_desconhecido(db):
    assert resolver_epc(db, "abcdef01") is None


def test_resolver_epc_retorna_none_para_epc_invalido_nunca_lanca(db):
    assert resolver_epc(db, "não é hex") is None
    assert resolver_epc(db, "") is None
    assert resolver_epc(db, "abc") is None  # ímpar


def test_resolver_epc_retorna_none_para_tag_com_vinculo_encerrado(db):
    equipamento = _criar_equipamento(db)
    associar(db, equipamento.id, "abcdef01")
    encerrar(db, equipamento.id)

    assert resolver_epc(db, "abcdef01") is None


def test_resolver_epc_retorna_o_vinculo_certo_quando_ativo(db):
    equipamento = _criar_equipamento(db)
    associar(db, equipamento.id, "abcdef01")

    encontrado = resolver_epc(db, "abcdef01")

    assert encontrado is not None
    assert encontrado.equipamento_id == equipamento.id
    assert encontrado.equipamento.nome == equipamento.nome


def test_resolver_epc_e_case_insensitive(db):
    equipamento = _criar_equipamento(db)
    associar(db, equipamento.id, "ABCDEF01")

    assert resolver_epc(db, "abcdef01").equipamento_id == equipamento.id
