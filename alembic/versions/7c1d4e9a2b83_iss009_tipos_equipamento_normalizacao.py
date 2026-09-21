"""iss-009: nome_normalizado, ativo e timestamps em tipos_equipamento

Revision ID: 7c1d4e9a2b83
Revises: 44ef89b10f17
Create Date: 2026-09-18

Pré-requisito da ISS-008 (`equipamentos.tipo_id` é FK obrigatória para
`tipos_equipamento`), por isso a baixa de um tipo é LÓGICA (`ativo`) e
nunca DELETE físico.

Ordem do upgrade (importa): a coluna `nome_normalizado` nasce NULLABLE,
as linhas já existentes são preenchidas por backfill, e só então a coluna
vira NOT NULL + UNIQUE. Criar a coluna já NOT NULL quebraria em qualquer
banco com linhas — e é exatamente o caso do banco de desenvolvimento.
"""
import re
import unicodedata
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7c1d4e9a2b83'
down_revision: Union[str, Sequence[str], None] = '44ef89b10f17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UNIQUE_NOME_NORMALIZADO = "uq_tipos_equipamento_nome_normalizado"
INDICE_ATIVO = "ix_tipos_equipamento_ativo"

_ESPACOS_REPETIDOS = re.compile(r"\s+")


def _normalizar_nome(nome: str) -> str:
    """
    CÓPIA INLINE, DE PROPÓSITO, de `api.normalizacao.normalizar_nome`.

    Uma migration não pode importar código de aplicação: ela precisa
    produzir o MESMO resultado daqui a um ano, mesmo que a função da
    aplicação mude. Se a regra de normalização mudar, a correção é uma
    migration NOVA que recalcule o backfill — nunca editar esta.
    """
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    return _ESPACOS_REPETIDOS.sub(" ", sem_acento.strip()).lower()


def _backfill_nome_normalizado(conexao) -> None:
    """
    Preenche `nome_normalizado` das linhas já existentes antes de a coluna
    virar NOT NULL + UNIQUE.

    Se duas linhas pré-existentes colapsarem no MESMO valor normalizado
    (ex.: "Cadeira de Rodas" e "cadeira  de rodas" cadastradas antes desta
    regra existir), a migration aborta com a lista de conflitos em vez de
    escolher sozinha qual sobrevive: decidir isso é do operador, não da
    migration. O UNIQUE mais abaixo falharia de qualquer forma — este erro
    só falha antes, dizendo o que arrumar.
    """
    linhas = conexao.execute(
        sa.text("SELECT id, nome FROM tipos_equipamento ORDER BY id")
    ).fetchall()

    normalizados: dict[str, list[str]] = {}
    for linha in linhas:
        normalizados.setdefault(_normalizar_nome(linha.nome), []).append(linha.nome)

    conflitos = {valor: nomes for valor, nomes in normalizados.items() if len(nomes) > 1}
    if conflitos:
        detalhe = "; ".join(
            f"{valor!r} <- {nomes}" for valor, nomes in sorted(conflitos.items())
        )
        raise RuntimeError(
            "tipos_equipamento tem nomes que colidem após a normalização da ISS-009. "
            "Resolva manualmente (renomeie ou remova os duplicados) e rode a migration "
            f"de novo. Conflitos: {detalhe}"
        )

    for linha in linhas:
        conexao.execute(
            sa.text(
                "UPDATE tipos_equipamento SET nome_normalizado = :normalizado WHERE id = :id"
            ),
            {"normalizado": _normalizar_nome(linha.nome), "id": linha.id},
        )


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "tipos_equipamento",
        sa.Column("nome_normalizado", sa.String(), nullable=True),
    )
    op.add_column(
        "tipos_equipamento",
        sa.Column("ativo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "tipos_equipamento",
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "tipos_equipamento",
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    _backfill_nome_normalizado(op.get_bind())

    op.alter_column("tipos_equipamento", "nome_normalizado", nullable=False)
    # Nome explícito: o `unique=True` do autogenerate cria constraint
    # anônima, e sem nome o downgrade não consegue derrubá-la.
    op.create_unique_constraint(
        UNIQUE_NOME_NORMALIZADO, "tipos_equipamento", ["nome_normalizado"]
    )
    op.create_index(INDICE_ATIVO, "tipos_equipamento", ["ativo"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(INDICE_ATIVO, table_name="tipos_equipamento")
    op.drop_constraint(UNIQUE_NOME_NORMALIZADO, "tipos_equipamento", type_="unique")
    op.drop_column("tipos_equipamento", "updated_at")
    op.drop_column("tipos_equipamento", "created_at")
    op.drop_column("tipos_equipamento", "ativo")
    op.drop_column("tipos_equipamento", "nome_normalizado")
