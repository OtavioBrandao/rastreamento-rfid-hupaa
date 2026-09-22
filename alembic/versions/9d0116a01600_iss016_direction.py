"""ISS-016: sentido lógico e zonas da passagem."""

import sqlalchemy as sa
from alembic import op

revision = "9d0116a01600"
down_revision = "4b751b0e9015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    legacy = connection.scalar(sa.text(
        "SELECT count(*) FROM passagens WHERE direcao IS NOT NULL"
    ))
    if legacy:
        raise RuntimeError(
            "ISS-016: passagens com direcao antiga não nula exigem revisão manual "
            "antes de migrar; entrada/saida não têm tradução inequívoca para A/B"
        )
    op.drop_constraint("ck_passagem_direcao_valida", "passagens", type_="check")
    op.create_check_constraint(
        "ck_passagem_direcao_valida", "passagens",
        "direcao IS NULL OR direcao IN ('a_para_b', 'b_para_a', 'indeterminada')",
    )
    op.add_column("passagens", sa.Column("direcao_status", sa.String(20), nullable=True))
    op.add_column("passagens", sa.Column("direcao_regra", sa.String(40), nullable=True))
    op.add_column("passagens", sa.Column("zona_origem_id", sa.BigInteger(), nullable=True))
    op.add_column("passagens", sa.Column("zona_destino_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_passagens_zona_origem_id", "passagens", "zonas", ["zona_origem_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_passagens_zona_destino_id", "passagens", "zonas", ["zona_destino_id"], ["id"]
    )
    op.create_check_constraint(
        "ck_passagem_direcao_estado", "passagens",
        "((direcao_status IS NULL AND direcao IS NULL AND direcao_regra IS NULL "
        "AND zona_origem_id IS NULL AND zona_destino_id IS NULL) OR "
        "(direcao_status = 'confirmed' AND direcao IN ('a_para_b', 'b_para_a') "
        "AND direcao_regra IS NOT NULL AND zona_origem_id IS NOT NULL "
        "AND zona_destino_id IS NOT NULL AND zona_origem_id <> zona_destino_id) OR "
        "(direcao_status IN ('ambiguous', 'unknown') AND direcao = 'indeterminada' "
        "AND direcao_regra IS NOT NULL AND zona_origem_id IS NULL "
        "AND zona_destino_id IS NULL)) IS TRUE",
    )


def downgrade() -> None:
    connection = op.get_bind()
    confirmed = connection.scalar(sa.text(
        "SELECT count(*) FROM passagens WHERE direcao IN ('a_para_b', 'b_para_a')"
    ))
    if confirmed:
        raise RuntimeError(
            "ISS-016: downgrade requer revisão manual das direções A/B confirmadas; "
            "o contrato antigo não as representa"
        )
    op.drop_constraint("ck_passagem_direcao_estado", "passagens", type_="check")
    op.drop_constraint("fk_passagens_zona_destino_id", "passagens", type_="foreignkey")
    op.drop_constraint("fk_passagens_zona_origem_id", "passagens", type_="foreignkey")
    op.drop_column("passagens", "zona_destino_id")
    op.drop_column("passagens", "zona_origem_id")
    op.drop_column("passagens", "direcao_regra")
    op.drop_column("passagens", "direcao_status")
    op.drop_constraint("ck_passagem_direcao_valida", "passagens", type_="check")
    op.create_check_constraint(
        "ck_passagem_direcao_valida", "passagens",
        "direcao IS NULL OR direcao IN ('entrada', 'saida', 'indeterminada')",
    )
