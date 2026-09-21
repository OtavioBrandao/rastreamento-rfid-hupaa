"""
Normalização e validação de EPC — ISS-010.

Decisão confirmada: faixa flexível de 8 a 32 caracteres hexadecimais,
tamanho par (EPCs de fabricantes diferentes podem variar; 96-bit/24-hex é o
caso mais comum no projeto, mas não o único suportado). Canonicalizado em
maiúsculas — ao contrário de nome/identificador_interno, um EPC não tem
grafia "correta" a preservar: a forma canônica é a única forma armazenada
(sem coluna normalizada separada).
"""

from __future__ import annotations

import re

_EPC_MIN_LEN = 8
_EPC_MAX_LEN = 32
_EPC_HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")


class EpcInvalido(ValueError):
    pass


def normalizar_epc(epc: str) -> str:
    limpo = epc.strip().upper()
    if not limpo:
        raise EpcInvalido("EPC não pode ficar vazio")
    if len(limpo) % 2 != 0:
        raise EpcInvalido("EPC deve ter um número par de caracteres hexadecimais")
    if not (_EPC_MIN_LEN <= len(limpo) <= _EPC_MAX_LEN):
        raise EpcInvalido(
            f"EPC deve ter entre {_EPC_MIN_LEN} e {_EPC_MAX_LEN} caracteres hexadecimais"
        )
    if not _EPC_HEX_RE.fullmatch(limpo):
        raise EpcInvalido("EPC deve conter apenas dígitos hexadecimais (0-9, A-F)")
    return limpo
