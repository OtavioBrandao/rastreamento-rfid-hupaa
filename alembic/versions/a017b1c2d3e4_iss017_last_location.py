"""ISS-017: referência da projeção à movimentação auditável."""

import sqlalchemy as sa
from alembic import op

revision = "a017b1c2d3e4"
down_revision = "f018a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Aplica a revisão: ISS-017: referência da projeção à movimentação auditável."""
    op.add_column(
        "equipamentos", sa.Column("ultima_movimentacao_id", sa.BigInteger(), nullable=True)
    )
    op.create_foreign_key(
        "fk_equipamentos_ultima_movimentacao_id", "equipamentos",
        "historico_movimentacoes", ["ultima_movimentacao_id"], ["id"],
    )


def downgrade() -> None:
    """Reverte a revisão: ISS-017: referência da projeção à movimentação auditável."""
    op.drop_constraint(
        "fk_equipamentos_ultima_movimentacao_id", "equipamentos", type_="foreignkey"
    )
    op.drop_column("equipamentos", "ultima_movimentacao_id")
