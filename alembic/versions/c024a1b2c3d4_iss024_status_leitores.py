"""ISS-024: contato observado e saúde reportada, separados do ciclo de vida."""

import sqlalchemy as sa
from alembic import op

revision = "c024a1b2c3d4"
down_revision = "b025a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Acrescenta monitoramento sem apagar cadastro, heartbeat nem histórico existente."""
    op.add_column("leitores", sa.Column("ultimo_contato_em", sa.TIMESTAMP(timezone=True)))
    op.add_column("leitores", sa.Column("origem_ultimo_contato", sa.String(16)))
    op.add_column("leitores", sa.Column("saude_reportada", sa.String(16)))
    op.execute("UPDATE leitores SET ultimo_contato_em = ultimo_heartbeat_em, "
               "origem_ultimo_contato = 'heartbeat', saude_reportada = 'online' "
               "WHERE ultimo_heartbeat_em IS NOT NULL")
    op.execute("UPDATE leitores SET status = 'nunca_conectado' "
               "WHERE ultimo_contato_em IS NULL")


def downgrade() -> None:
    """Remove somente os novos campos de monitoramento e restaura o estado legado."""
    op.execute("UPDATE leitores SET status = 'offline' WHERE status = 'nunca_conectado'")
    op.drop_column("leitores", "saude_reportada")
    op.drop_column("leitores", "origem_ultimo_contato")
    op.drop_column("leitores", "ultimo_contato_em")
