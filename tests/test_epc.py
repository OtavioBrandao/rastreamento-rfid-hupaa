"""
Testes puros de `api.epc.normalizar_epc` — ISS-010.

Sem banco, sem fixture `db`: são testes de uma função pura, e testar
função pura contra Postgres seria só deixar a suíte mais lenta à toa.
"""

from __future__ import annotations

import pytest

from api.epc import EpcInvalido, normalizar_epc


def test_normaliza_para_maiusculas():
    assert normalizar_epc("abcdef01") == "ABCDEF01"


def test_remove_espaco_nas_pontas():
    assert normalizar_epc("  ABCDEF01  ") == "ABCDEF01"


def test_ja_maiusculo_e_sem_espaco_permanece_igual():
    assert normalizar_epc("ABCDEF01") == "ABCDEF01"


def test_limite_minimo_8_chars_e_valido():
    assert normalizar_epc("A1B2C3D4") == "A1B2C3D4"


def test_limite_maximo_32_chars_e_valido():
    epc = "A1" * 16  # 32 caracteres
    assert normalizar_epc(epc) == epc


def test_epc_vazio_levanta_epc_invalido():
    with pytest.raises(EpcInvalido):
        normalizar_epc("")


def test_epc_so_espaco_levanta_epc_invalido():
    with pytest.raises(EpcInvalido):
        normalizar_epc("    ")


def test_epc_com_numero_impar_de_chars_levanta_epc_invalido():
    with pytest.raises(EpcInvalido):
        normalizar_epc("ABC")  # 3 chars, ímpar


def test_epc_curto_demais_levanta_epc_invalido():
    with pytest.raises(EpcInvalido):
        normalizar_epc("AB1234")  # 6 chars, par, mas abaixo do mínimo de 8


def test_epc_longo_demais_levanta_epc_invalido():
    with pytest.raises(EpcInvalido):
        normalizar_epc("A1" * 17)  # 34 caracteres, acima do máximo de 32


def test_epc_nao_hexadecimal_levanta_epc_invalido():
    with pytest.raises(EpcInvalido):
        normalizar_epc("ZZZZZZZZ")


def test_epc_invalido_e_subclasse_de_value_error():
    """
    `AssociarPayload`/`SubstituirPayload` dependem disso: um
    `field_validator` do Pydantic que capturar `EpcInvalido` e relançar
    `ValueError(str(...))` só existe porque hoje não precisaria — mas o
    contrato de que `EpcInvalido` HERDA de `ValueError` é o que garante
    que, se algum código deixar de capturar explicitamente, o Pydantic
    ainda converte para erro de validação 422 em vez de vazar como 500.
    """
    assert issubclass(EpcInvalido, ValueError)
