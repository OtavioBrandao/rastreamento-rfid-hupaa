"""
Testes puros (sem banco) dos schemas da ISS-012.

O foco é `parametros_ingestao`: decisão da issue — NENHUMA credencial de broker
no banco. Não basta "não termos um campo de senha": tentar mandar uma
credencial dentro do JSON de metadados tem que ser REJEITADO, não aceito em
silêncio. A barreira é uma ALLOWLIST fechada de chaves (com forma de valor
validada por chave): qualquer chave fora dela é 422, mesmo uma inócua como
"descricao". O teste HTTP equivalente (422 de verdade, sem ecoar o segredo) está
em `tests/test_api_hardware.py`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.schemas_hardware import (
    PARAMETROS_INGESTAO_PERMITIDOS,
    AntenaAtualizar,
    AntenaCriar,
    LeitorAtualizar,
    LeitorCriar,
    PortalAtualizar,
)

BASE = {
    "reader_id": "reader-01",
    "fabricante": "Identix",
    "modelo": "EZ700",
    "identificador_serial": "SN-0001",
}


def _leitor(**extra):
    return LeitorCriar(**BASE, **extra)


# --- as chaves da allowlist, com valores válidos passam ---------------------------------------


TOPICO = "easy/dev/hupaa/portal-01/reader-01/readings"


@pytest.mark.parametrize(
    "parametros",
    [
        {"protocolo": "mqtt"},
        {"adapter": "ez700"},
        {"adapter": "simulator"},
        {"adapter": "novo_adapter-2"},
        {"formato_timestamp": "rfc3339"},
        {"formato_timestamp": "epoch_ms"},
        {"topico": TOPICO},
        {"topico": "easy/dev/hupaa/+/+/readings"},  # forma de assinatura, como a da ingestão
        {"qos": 0},
        {"qos": 1},
        {"qos": 2},
        {  # todas juntas
            "protocolo": "mqtt",
            "adapter": "ez700",
            "formato_timestamp": "epoch_ms",
            "topico": TOPICO,
            "qos": 1,
        },
        {},
    ],
)
def test_chave_permitida_com_valor_valido_e_aceita(parametros):
    assert _leitor(parametros_ingestao=parametros).parametros_ingestao == parametros


def test_parametros_ingestao_e_opcional():
    assert _leitor().parametros_ingestao is None


def test_as_chaves_permitidas_sao_exatamente_estas():
    """Fixa a allowlist: mudar o conjunto é uma decisão de revisão, não um efeito colateral."""
    assert set(PARAMETROS_INGESTAO_PERMITIDOS) == {
        "protocolo",
        "adapter",
        "formato_timestamp",
        "topico",
        "qos",
    }


# --- QUALQUER chave fora da allowlist é rejeitada -------------------------------------------------


@pytest.mark.parametrize(
    "parametros",
    [
        # a brecha que a blocklist deixava passar: segredo sob uma chave inocente
        {"x": "hunter2"},
        {"nome": "hunter2"},
        {"valor": "hunter2"},
        # chave obviamente INÓCUA, mas não listada: é allowlist, não uma blocklist maior
        {"descricao": "leitor do corredor norte"},
        {"observacoes": "sem problemas"},
        {"keepalive": 60},  # plausível como chave futura, mas não listada hoje
        {"tls": True},
        # as credenciais óbvias continuam rejeitadas (agora por serem desconhecidas)
        {"password": "hunter2"},
        {"senha": "hunter2"},
        {"token": "hunter2"},
        {"username": "broker-user"},
        {"client_secret": "hunter2"},
        {"broker_url": "mqtt://usuario:hunter2@broker.local:1883"},
        # a allowlist é EXATA: caixa e espaço importam
        {"Adapter": "ez700"},
        {"QOS": 1},
        {"adapter ": "ez700"},
        {" adapter": "ez700"},
        # aninhado: a chave de topo já não está na lista
        {"broker": {"host": "x", "password": "hunter2"}},
        {"opcoes": {"retain": False}},
        # uma chave permitida NÃO autoriza uma desconhecida ao lado
        {"adapter": "ez700", "x": "hunter2"},
        {"qos": 1, "descricao": "ok"},
    ],
)
def test_chave_fora_da_allowlist_e_rejeitada(parametros):
    with pytest.raises(ValidationError) as erro:
        _leitor(parametros_ingestao=parametros)

    mensagem = erro.value.errors()[0]["msg"]
    assert "allowlist" in mensagem
    assert "hunter2" not in mensagem  # nomeia a chave, nunca ecoa o valor
    assert "leitor do corredor" not in mensagem


def test_a_mensagem_lista_as_chaves_permitidas_para_o_cliente_corrigir():
    with pytest.raises(ValidationError) as erro:
        _leitor(parametros_ingestao={"descricao": "x"})

    mensagem = erro.value.errors()[0]["msg"]
    for chave in ("adapter", "formato_timestamp", "protocolo", "qos", "topico"):
        assert chave in mensagem
    assert "'descricao'" in mensagem


# --- o VALOR de uma chave permitida também tem forma validada -----------------------------------


@pytest.mark.parametrize(
    "parametros",
    [
        {"qos": 3},
        {"qos": -1},
        {"qos": "1"},
        {"qos": 1.0},
        {"qos": True},  # bool é subclasse de int, mas não é um QoS
        {"qos": None},
        {"adapter": ""},
        {"adapter": "ez 700"},
        {"adapter": "ez700!"},
        {"adapter": "a" * 65},
        {"adapter": 5},
        {"adapter": ["ez700"]},
        {"adapter": {"nome": "ez700"}},  # não-escalar: nem uma chave permitida carrega estrutura
        {"protocolo": "http"},
        {"protocolo": "MQTT"},
        {"protocolo": 1},
        {"formato_timestamp": "unix"},
        {"formato_timestamp": ""},
        {"topico": "x"},
        {"topico": "easy/dev/hupaa/portal-01/reader-01/outro"},
        {"topico": "easy/dev/hupaa/portal 01/reader-01/readings"},
        {"topico": "easy/dev/hupaa/p/" + "a" * 300 + "/readings"},
        {"topico": 7},
        # um tópico válido não tem ':' nem '@': credencial em URL não passa nem por chave permitida
        {"topico": "mqtt://usuario:hunter2@broker.local/easy/dev/hupaa/p/r/readings"},
        {"topico": "-----BEGIN PRIVATE KEY-----"},
    ],
)
def test_valor_invalido_em_chave_permitida_e_rejeitado(parametros):
    with pytest.raises(ValidationError) as erro:
        _leitor(parametros_ingestao=parametros)

    mensagem = erro.value.errors()[0]["msg"]
    chave = next(iter(parametros))
    assert f"parametros_ingestao.{chave}" in mensagem
    assert "hunter2" not in mensagem  # a mensagem nunca ecoa o valor recebido
    assert "BEGIN" not in mensagem


def test_parametros_precisa_ser_um_objeto_json():
    for invalido in ([], "texto", 3, ["adapter"]):
        with pytest.raises(ValidationError):
            _leitor(parametros_ingestao=invalido)


# --- a MESMA allowlist vale no PATCH ---------------------------------------------------------------


def test_patch_rejeita_chave_fora_da_allowlist():
    for parametros in ({"x": "hunter2"}, {"descricao": "x"}, {"password": "hunter2"}):
        with pytest.raises(ValidationError, match="allowlist"):
            LeitorAtualizar(parametros_ingestao=parametros)


def test_patch_rejeita_valor_invalido_e_aceita_valido():
    with pytest.raises(ValidationError, match="qos"):
        LeitorAtualizar(parametros_ingestao={"qos": 9})
    assert LeitorAtualizar(parametros_ingestao={"qos": 1}).parametros_ingestao == {"qos": 1}


def test_patch_aceita_null_para_limpar():
    ok = LeitorAtualizar(parametros_ingestao=None)
    assert "parametros_ingestao" in ok.model_fields_set and ok.parametros_ingestao is None


# --- reader_id: segmento de tópico MQTT ---------------------------------------------------


@pytest.mark.parametrize("valido", ["reader-01", "EZ700_PORTAL_01", "R1", "a-b_C-9"])
def test_reader_id_valido(valido):
    assert LeitorCriar(**{**BASE, "reader_id": valido}).reader_id == valido


@pytest.mark.parametrize(
    "invalido", ["", "   ", "reader 01", "reader/01", "reader+01", "reader#", "leitor-ç", "a" * 65]
)
def test_reader_id_invalido(invalido):
    with pytest.raises(ValidationError):
        LeitorCriar(**{**BASE, "reader_id": invalido})


def test_reader_id_faz_strip():
    assert LeitorCriar(**{**BASE, "reader_id": "  reader-01 "}).reader_id == "reader-01"


@pytest.mark.parametrize("campo", ["fabricante", "modelo", "identificador_serial"])
def test_textos_obrigatorios_rejeitam_vazio(campo):
    with pytest.raises(ValidationError):
        LeitorCriar(**{**BASE, campo: "   "})


# --- PATCH: null explícito em coluna NOT NULL é 422; nas anuláveis limpa ---------------------


@pytest.mark.parametrize("campo", ["reader_id", "fabricante", "modelo", "identificador_serial"])
def test_leitor_patch_recusa_null_em_not_null(campo):
    with pytest.raises(ValidationError, match="não pode ser null"):
        LeitorAtualizar(**{campo: None})


def test_leitor_patch_aceita_null_nas_anulaveis():
    parcial = LeitorAtualizar(endereco_rede=None, parametros_ingestao=None)
    assert parcial.model_dump(exclude_unset=True) == {"endereco_rede": None, "parametros_ingestao": None}


def test_leitor_patch_ignora_status_e_heartbeat():
    """Conectividade ao vivo é da ingestão: nem entra no schema de update."""
    parcial = LeitorAtualizar(status="online", ultimo_heartbeat_em="2026-01-01T00:00:00Z", modelo="X")

    assert parcial.model_dump(exclude_unset=True) == {"modelo": "X"}


@pytest.mark.parametrize("campo", ["porta_numero", "zona_associada_id", "funcao"])
def test_antena_patch_recusa_null_em_not_null(campo):
    with pytest.raises(ValidationError, match="não pode ser null"):
        AntenaAtualizar(**{campo: None})


def test_antena_patch_aceita_portal_id_null_para_desassociar():
    parcial = AntenaAtualizar(portal_id=None)

    assert parcial.model_dump(exclude_unset=True) == {"portal_id": None}


def test_antena_patch_nao_tem_leitor_id():
    """O schema nem expõe o campo: mandá-lo é descartado, não obedecido."""
    assert "leitor_id" not in AntenaAtualizar.model_fields
    assert AntenaAtualizar(leitor_id=5, funcao="saida").model_dump(exclude_unset=True) == {
        "funcao": "saida"
    }


def test_antena_criar_valida_funcao_e_ids():
    ok = AntenaCriar(leitor_id=1, porta_numero=1, zona_associada_id=1, funcao="entrada")
    assert ok.portal_id is None
    for invalido in (
        {"funcao": "lateral"},
        {"porta_numero": 0},  # a ingestão só aceita antenna >= 1
        {"leitor_id": 0},
        {"zona_associada_id": -1},
        {"portal_id": 0},
    ):
        with pytest.raises(ValidationError):
            AntenaCriar(**{"leitor_id": 1, "porta_numero": 1, "zona_associada_id": 1, "funcao": "entrada", **invalido})


def test_portal_patch_recusa_null_em_not_null():
    for campo in ("nome", "zona_a_id", "zona_b_id"):
        with pytest.raises(ValidationError, match="não pode ser null"):
            PortalAtualizar(**{campo: None})
    assert PortalAtualizar(localizacao_fisica=None).model_dump(exclude_unset=True) == {
        "localizacao_fisica": None
    }
