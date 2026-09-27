"""ISS-019: índices para tipo e recência na busca operacional."""

from alembic import op

revision = "b019a1b2c3d4"
down_revision = "a017b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_equipamentos_tipo_id", "equipamentos", ["tipo_id"])
    op.create_index(
        "ix_equipamentos_ultima_deteccao_em", "equipamentos", ["ultima_deteccao_em"]
    )


def downgrade() -> None:
    op.drop_index("ix_equipamentos_ultima_deteccao_em", table_name="equipamentos")
    op.drop_index("ix_equipamentos_tipo_id", table_name="equipamentos")
