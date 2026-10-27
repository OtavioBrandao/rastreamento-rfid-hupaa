"""Status próprio para "fora de serviço", separado da baixa lógica (`inativo`).

`inativo` continua sendo a baixa lógica (cadastro encerrado, ensaio arquivado) e
some do painel no modo "somente ativos". `fora_de_servico` é o equipamento que
existe, mas não deve ser usado (ex.: maca quebrada, tag danificada): continua no
inventário, no mapa e nas abas, em vermelho, e suas transições seguem detectadas.
"""

from alembic import op

revision = "s042a1b2c3d4"
down_revision = "s041a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Aceita o status `fora_de_servico`."""
    op.drop_constraint("ck_equipamento_status_valido", "equipamentos", type_="check")
    op.create_check_constraint("ck_equipamento_status_valido", "equipamentos",
                               "status IN ('ativo', 'inativo', 'fora_de_servico')")


def downgrade() -> None:
    """Fora de serviço volta a ser baixa lógica antes de restringir o status."""
    op.execute("UPDATE equipamentos SET status = 'inativo' WHERE status = 'fora_de_servico'")
    op.drop_constraint("ck_equipamento_status_valido", "equipamentos", type_="check")
    op.create_check_constraint("ck_equipamento_status_valido", "equipamentos",
                               "status IN ('ativo', 'inativo')")
