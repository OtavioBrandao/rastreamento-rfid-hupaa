"""iss-012 (ajustes): porta única só entre antenas ATIVAS e created_at/updated_at em leitores/antenas/portais

Revision ID: 6b3e5f7a91c4
Revises: 019782a38ff7
Create Date: 2026-09-20

Dois ajustes do CRUD de leitores/antenas/portais (ISS-012):

1. `uq_antena_por_porta_leitor` (UNIQUE CONSTRAINT em (leitor_id, porta_numero))
   vira o ÍNDICE ÚNICO PARCIAL `uq_antena_ativa_por_porta_leitor`, `WHERE ativo`
   — o mesmo padrão de `uq_tag_ativa`/`uq_equipamento_tag_ativa` (ISS-010). Uma
   antena inativada libera a porta para uma antena NOVA nascer ali; a linha
   antiga continua existindo (o histórico de leituras a referencia).

   O upgrade é seguro sem backfill: a UNIQUE antiga garantia unicidade entre
   TODAS as linhas, então nenhuma linha existente viola a regra mais frouxa.

   O downgrade NÃO é: voltar para a UNIQUE total falha se, no meio tempo, uma
   antena inativa e uma ativa passaram a dividir a mesma porta. Em vez de deixar
   o `ALTER TABLE` estourar com um erro genérico (ou apagar linha), a migration
   aborta listando os conflitos — resolver (renumerar ou remover) é decisão do
   operador.

2. `created_at`/`updated_at` (TIMESTAMP WITH TIME ZONE, `DEFAULT now()`), mesmo
   padrão de Andar/Setor/Zona/Equipamento/TipoEquipamento. Linhas que já existem
   recebem o instante da migration: não há registro de quando foram de fato
   criadas.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '6b3e5f7a91c4'
down_revision: Union[str, Sequence[str], None] = '019782a38ff7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UNIQUE_ANTIGA = "uq_antena_por_porta_leitor"
INDICE_PARCIAL = "uq_antena_ativa_por_porta_leitor"
TABELAS_COM_TIMESTAMPS = ("leitores", "antenas", "portais")


def upgrade() -> None:
    """Upgrade schema."""
    for tabela in TABELAS_COM_TIMESTAMPS:
        for coluna in ("created_at", "updated_at"):
            op.add_column(
                tabela,
                sa.Column(
                    coluna,
                    sa.TIMESTAMP(timezone=True),
                    server_default=sa.text("now()"),
                    nullable=False,
                ),
            )

    op.drop_constraint(UNIQUE_ANTIGA, "antenas", type_="unique")
    op.create_index(
        INDICE_PARCIAL,
        "antenas",
        ["leitor_id", "porta_numero"],
        unique=True,
        postgresql_where=sa.text("ativo"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    conflitos = op.get_bind().execute(
        sa.text(
            "SELECT leitor_id, porta_numero, array_agg(id ORDER BY id) AS antenas "
            "FROM antenas GROUP BY leitor_id, porta_numero HAVING COUNT(*) > 1 "
            "ORDER BY leitor_id, porta_numero"
        )
    ).fetchall()
    if conflitos:
        detalhe = "; ".join(
            f"leitor {c.leitor_id} porta {c.porta_numero} -> antenas {list(c.antenas)}"
            for c in conflitos
        )
        raise RuntimeError(
            "voltar para a UNIQUE total (leitor_id, porta_numero) não é possível: há porta "
            "compartilhada por uma antena inativa e outra(s) — o índice parcial permitia, a "
            "UNIQUE antiga não. Renumere ou remova as antenas repetidas e rode o downgrade "
            f"de novo. Afetadas: {detalhe}"
        )

    op.drop_index(INDICE_PARCIAL, table_name="antenas")
    op.create_unique_constraint(UNIQUE_ANTIGA, "antenas", ["leitor_id", "porta_numero"])

    for tabela in TABELAS_COM_TIMESTAMPS:
        op.drop_column(tabela, "updated_at")
        op.drop_column(tabela, "created_at")
