"""
Normalização de nomes para detecção de duplicidade (ISS-009).

A chave de unicidade de `tipos_equipamento` não é o `nome` digitado, e sim
o `nome_normalizado` derivado dele. Isso impede que "Cadeira de Rodas",
"cadeira  de   rodas" e "Cadeira de rodas " convivam como três tipos
distintos no cadastro.

ATENÇÃO: a migration que criou a coluna `nome_normalizado` tem uma CÓPIA
INLINE desta regra, de propósito — uma migration não pode importar código
de aplicação, senão para de rodar (ou passa a rodar diferente) quando o
código muda. Se a regra mudar aqui, é preciso uma migration NOVA que
recalcule o backfill; editar a antiga não tem efeito em banco já migrado.
"""

import re
import unicodedata

_ESPACOS_REPETIDOS = re.compile(r"\s+")


def normalizar_nome(nome: str) -> str:
    """
    Reduz um nome à sua forma canônica de comparação:
    remove acentos (NFKD + descarte do que não é ASCII), remove espaço das
    pontas, colapsa espaços internos repetidos em um só e passa para
    minúsculas.

    >>> normalizar_nome("  Cadeira  de   Rodas ")
    'cadeira de rodas'
    """
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    return _ESPACOS_REPETIDOS.sub(" ", sem_acento.strip()).lower()
