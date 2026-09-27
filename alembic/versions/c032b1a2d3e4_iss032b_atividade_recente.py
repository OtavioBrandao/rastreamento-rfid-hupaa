"""ISS-032B: índice para atividade recente global com limite."""

import sqlalchemy as sa
from alembic import op

revision = "c032b1a2d3e4"
down_revision = "b019a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_historico_atividade_recente", "historico_movimentacoes",
        ["movimentada_em", "id"],
        postgresql_where=sa.text("movimentada_em IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_historico_atividade_recente", table_name="historico_movimentacoes")
