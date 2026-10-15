"""ISS-025: versão otimista do equipamento e referência da correção manual."""

import sqlalchemy as sa
from alembic import op

revision = "b025a1b2c3d4"
down_revision = "e028a1b2c3d4"
branch_labels = None
depends_on = None

CHECK_REFERENCIA = (
    "referencia IS NULL OR (origem_registro = 'correcao_manual' "
    "AND length(btrim(referencia)) > 0)"
)


def upgrade() -> None:
    op.add_column("equipamentos", sa.Column(
        "versao", sa.BigInteger(), server_default=sa.text("1"), nullable=False))
    op.create_check_constraint("ck_equipamentos_versao_positiva", "equipamentos", "versao >= 1")

    op.add_column("historico_movimentacoes", sa.Column(
        "referencia", sa.String(length=255), nullable=True))
    op.create_check_constraint(
        "ck_historico_referencia_so_manual", "historico_movimentacoes", CHECK_REFERENCIA
    )


def downgrade() -> None:
    # A referência não cabe no schema antigo: vai para o fim da justificativa.
    op.execute(
        "UPDATE historico_movimentacoes "
        "SET justificativa = justificativa || ' [referência: ' || referencia || ']' "
        "WHERE referencia IS NOT NULL"
    )
    op.drop_constraint("ck_historico_referencia_so_manual", "historico_movimentacoes",
                       type_="check")
    op.drop_column("historico_movimentacoes", "referencia")
    op.drop_constraint("ck_equipamentos_versao_positiva", "equipamentos", type_="check")
    op.drop_column("equipamentos", "versao")
