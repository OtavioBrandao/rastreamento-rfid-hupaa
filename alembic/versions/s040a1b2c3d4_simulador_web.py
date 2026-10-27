"""Simulador web: layouts editáveis da planta e sessões de simulação.

Tabelas próprias, sem alterar nenhuma tabela do pipeline: o simulador entra
pelo broker MQTT, como um leitor, e o ingestor/inferência continuam iguais.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "s040a1b2c3d4"
down_revision = "c024a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Cria layouts (configuração da planta) e sessões (estado compartilhado entre abas)."""
    op.create_table(
        "simulacao_layouts",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("nome", sa.String(120), nullable=False),
        sa.Column("cenario", sa.String(16), nullable=False),
        sa.Column("configuracao", JSONB, nullable=False),
        sa.Column("vinculos", JSONB, nullable=True),
        sa.Column("versao", sa.BigInteger, nullable=False, server_default=sa.text("1")),
        sa.Column("arquivado", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("aplicado_em", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("cenario IN ('easy', 'hupaa')", name="ck_simulacao_layout_cenario"),
        sa.CheckConstraint("versao >= 1", name="ck_simulacao_layout_versao"),
    )
    op.create_index("ix_simulacao_layouts_cenario", "simulacao_layouts", ["cenario", "arquivado"])
    op.create_table(
        "simulacao_sessoes",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("codigo", sa.String(32), nullable=False),
        sa.Column("layout_id", sa.BigInteger,
                  sa.ForeignKey("simulacao_layouts.id", name="fk_simulacao_sessoes_layout_id"),
                  nullable=False),
        sa.Column("cenario", sa.String(16), nullable=False),
        sa.Column("layout", JSONB, nullable=False),
        sa.Column("topologia", JSONB, nullable=False),
        sa.Column("itens", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("estado", sa.String(16), nullable=False),
        sa.Column("versao", sa.BigInteger, nullable=False, server_default=sa.text("1")),
        # Sem FK de propósito: a sessão de simulação não pode travar a gestão de usuários.
        sa.Column("criada_por", sa.BigInteger, nullable=True),
        sa.Column("iniciada_em", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("atualizada_em", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("encerrada_em", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("codigo", name="uq_simulacao_sessoes_codigo"),
        sa.CheckConstraint("estado IN ('em_execucao', 'pausada', 'encerrada')",
                           name="ck_simulacao_sessao_estado"),
        sa.CheckConstraint("(estado = 'encerrada') = (encerrada_em IS NOT NULL)",
                           name="ck_simulacao_sessao_encerramento"),
    )
    op.create_index("ix_simulacao_sessoes_estado", "simulacao_sessoes", ["estado"])
    # No máximo uma sessão aberta por layout: duas publicariam pelos mesmos leitores virtuais.
    op.create_index("uq_simulacao_sessao_aberta_por_layout", "simulacao_sessoes", ["layout_id"],
                    unique=True, postgresql_where=sa.text("estado <> 'encerrada'"))


def downgrade() -> None:
    """Remove as tabelas do simulador web; leituras já publicadas permanecem no pipeline."""
    op.drop_index("uq_simulacao_sessao_aberta_por_layout", table_name="simulacao_sessoes")
    op.drop_index("ix_simulacao_sessoes_estado", table_name="simulacao_sessoes")
    op.drop_table("simulacao_sessoes")
    op.drop_index("ix_simulacao_layouts_cenario", table_name="simulacao_layouts")
    op.drop_table("simulacao_layouts")
