"""Portal de entrada da zona: as duas antenas do leitor confirmam a zona em qualquer ordem.

`portais.modo`:
- `direcional` (padrão, comportamento anterior): a ordem dos lados A → B ou
  B → A decide origem e destino;
- `entrada`: o portal é a entrada da zona do lado B. Leituras válidas nas duas
  antenas, em qualquer ordem, confirmam a transição para a zona B.
"""

import sqlalchemy as sa
from alembic import op

revision = "s041a1b2c3d4"
down_revision = "s040a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Acrescenta o modo do portal; os portais existentes continuam direcionais."""
    op.add_column("portais", sa.Column("modo", sa.String(16), nullable=False,
                                       server_default="direcional"))
    op.create_check_constraint("ck_portal_modo", "portais", "modo IN ('direcional', 'entrada')")


def downgrade() -> None:
    """Remove o modo (todos voltam a ser direcionais)."""
    op.drop_constraint("ck_portal_modo", "portais", type_="check")
    op.drop_column("portais", "modo")
