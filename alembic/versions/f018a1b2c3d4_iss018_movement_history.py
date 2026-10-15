"""ISS-018: evidências, tempo do evento e idempotência do histórico."""

import sqlalchemy as sa
from alembic import op

revision = "f018a1b2c3d4"
down_revision = "9d0116a01600"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Aplica a revisão: ISS-018: evidências, tempo do evento e idempotência do histórico."""
    for column in (
        sa.Column("epc", sa.String(), nullable=True),
        sa.Column("portal_id", sa.BigInteger(), nullable=True),
        sa.Column("leitura_origem_id", sa.BigInteger(), nullable=True),
        sa.Column("leitura_destino_id", sa.BigInteger(), nullable=True),
        sa.Column("movimentada_em", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("justificativa", sa.Text(), nullable=True),
        sa.Column("registro_anterior_id", sa.BigInteger(), nullable=True),
    ):
        op.add_column("historico_movimentacoes", column)
    for column, table in (
        ("portal_id", "portais"),
        ("leitura_origem_id", "leituras_brutas"),
        ("leitura_destino_id", "leituras_brutas"),
        ("registro_anterior_id", "historico_movimentacoes"),
    ):
        op.create_foreign_key(
            f"fk_historico_{column}", "historico_movimentacoes", table, [column], ["id"]
        )
    # Linhas legadas permanecem intactas. CHECK NOT VALID protege novas inserções
    # sem presumir event time ou justificativa que não foram capturados antes.
    op.execute(sa.text(
        "ALTER TABLE historico_movimentacoes ADD CONSTRAINT ck_historico_registro_completo "
        "CHECK ((origem_registro = 'passagem_automatica' AND passagem_id IS NOT NULL "
        "AND epc IS NOT NULL AND portal_id IS NOT NULL AND leitura_origem_id IS NOT NULL "
        "AND leitura_destino_id IS NOT NULL AND movimentada_em IS NOT NULL "
        "AND zona_origem_id IS NOT NULL AND zona_origem_id <> zona_destino_id "
        "AND justificativa IS NULL AND registro_anterior_id IS NULL) OR "
        "(origem_registro = 'correcao_manual' AND passagem_id IS NULL "
        "AND justificativa IS NOT NULL AND length(btrim(justificativa)) > 0 "
        "AND movimentada_em IS NOT NULL)) NOT VALID"
    ))
    op.create_index(
        "uq_historico_passagem_automatica", "historico_movimentacoes",
        ["passagem_id"], unique=True,
        postgresql_where=sa.text("origem_registro = 'passagem_automatica'"),
    )
    op.create_index(
        "ix_historico_equipamento_movimentada_id", "historico_movimentacoes",
        ["equipamento_id", "movimentada_em", "id"],
    )


def downgrade() -> None:
    """Reverte a revisão: ISS-018: evidências, tempo do evento e idempotência do histórico."""
    op.drop_index("ix_historico_equipamento_movimentada_id", table_name="historico_movimentacoes")
    op.drop_index("uq_historico_passagem_automatica", table_name="historico_movimentacoes")
    op.drop_constraint("ck_historico_registro_completo", "historico_movimentacoes", type_="check")
    for column in ("registro_anterior_id", "leitura_destino_id", "leitura_origem_id", "portal_id"):
        op.drop_constraint(f"fk_historico_{column}", "historico_movimentacoes", type_="foreignkey")
    for column in (
        "registro_anterior_id", "justificativa", "movimentada_em", "leitura_destino_id",
        "leitura_origem_id", "portal_id", "epc",
    ):
        op.drop_column("historico_movimentacoes", column)
