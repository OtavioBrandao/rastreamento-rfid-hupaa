"""iss-015: unicidade das duas leituras que confirmam a passagem."""

from alembic import op

revision = "4b751b0e9015"
down_revision = "68e5a26c2e17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Aplica a revisão: iss-015: unicidade das duas leituras que confirmam a passagem."""
    op.create_index(
        "uq_passagem_evidencias",
        "passagens",
        ["leitura_origem_id", "leitura_destino_id"],
        unique=True,
    )


def downgrade() -> None:
    """Reverte a revisão: iss-015: unicidade das duas leituras que confirmam a passagem."""
    op.drop_index("uq_passagem_evidencias", table_name="passagens")
