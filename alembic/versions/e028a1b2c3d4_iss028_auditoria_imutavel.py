"""ISS-028: trilha de auditoria append-only, catálogo de ações e origem."""

import sqlalchemy as sa
from alembic import op

revision = "e028a1b2c3d4"
down_revision = "d026a1b2c3d4"
branch_labels = None
depends_on = None

ACOES = (
    "criar", "atualizar", "inativar", "reativar", "excluir",
    "vincular_epc", "desvincular_epc", "alterar_senha", "correcao_manual",
    "login_aceito", "login_recusado", "conta_bloqueada", "logout", "acesso_negado",
)
ACOES_ANTIGAS = ("create", "update", "delete", "correcao_manual")
# Só estas têm equivalente no vocabulário antigo; o resto bloqueia o downgrade.
ACOES_REVERSIVEIS = ("criar", "atualizar", "excluir", "correcao_manual")
TRADUCAO = (("create", "criar"), ("update", "atualizar"), ("delete", "excluir"))


def _lista(valores) -> str:
    return ", ".join(f"'{valor}'" for valor in valores)


def upgrade() -> None:
    op.drop_constraint("ck_auditoria_acao_valida", "auditorias", type_="check")
    for antiga, nova in TRADUCAO:
        op.execute(sa.text("UPDATE auditorias SET acao = :nova WHERE acao = :antiga")
                   .bindparams(nova=nova, antiga=antiga))
    op.create_check_constraint(
        "ck_auditoria_acao_valida", "auditorias", f"acao IN ({_lista(ACOES)})"
    )

    op.add_column("auditorias", sa.Column("origem", sa.String(length=16), nullable=True))
    op.execute(
        "UPDATE auditorias SET origem = CASE WHEN usuario_id IS NULL "
        "THEN 'sistema' ELSE 'usuario' END"
    )
    op.alter_column("auditorias", "origem", nullable=False)
    op.create_check_constraint(
        "ck_auditoria_origem_valida", "auditorias", "origem IN ('usuario', 'sistema', 'anonimo')"
    )
    op.create_check_constraint(
        "ck_auditoria_autor_coerente", "auditorias",
        "(origem = 'usuario') = (usuario_id IS NOT NULL)",
    )
    op.add_column("auditorias", sa.Column("correlation_id", sa.String(length=64), nullable=True))
    op.add_column("auditorias", sa.Column("motivo", sa.Text(), nullable=True))
    op.alter_column("auditorias", "entidade_id", nullable=True)

    op.create_index("ix_auditorias_registrado_em", "auditorias", ["registrado_em", "id"])
    op.create_index(
        "ix_auditorias_usuario_registrado_em", "auditorias", ["usuario_id", "registrado_em"]
    )
    op.create_index("ix_auditorias_correlation_id", "auditorias", ["correlation_id"])

    op.execute("""
        CREATE FUNCTION auditorias_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'auditorias é append-only: % não é permitido', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER tg_auditorias_append_only
        BEFORE UPDATE OR DELETE ON auditorias
        FOR EACH ROW EXECUTE FUNCTION auditorias_append_only()
    """)


def downgrade() -> None:
    # Sem o trigger, as traduções abaixo (UPDATE) passam a ser possíveis.
    op.execute("DROP TRIGGER tg_auditorias_append_only ON auditorias")
    op.execute("DROP FUNCTION auditorias_append_only()")

    bind = op.get_bind()
    sem_alvo = bind.execute(sa.text(
        "SELECT count(*) FROM auditorias WHERE entidade_id IS NULL")).scalar_one()
    sem_equivalente = bind.execute(sa.text(
        f"SELECT count(*) FROM auditorias WHERE acao NOT IN ({_lista(ACOES_REVERSIVEIS)})"
    )).scalar_one()
    if sem_alvo or sem_equivalente:
        # O schema antigo não comporta essas linhas, e trilha nunca é apagada.
        raise RuntimeError(
            "ISS-028: downgrade recusado — a trilha tem "
            f"{sem_alvo} linha(s) sem entidade_id e {sem_equivalente} linha(s) com ação "
            "sem equivalente no vocabulário antigo. Nada foi alterado."
        )

    # Preserva motivo e correlação antes de remover as colunas.
    op.execute("""
        UPDATE auditorias
        SET dados_depois = COALESCE(dados_depois, '{}'::jsonb) || jsonb_build_object(
            '_iss028', jsonb_strip_nulls(jsonb_build_object(
                'motivo', motivo, 'correlation_id', correlation_id)))
        WHERE motivo IS NOT NULL OR correlation_id IS NOT NULL
    """)

    op.drop_index("ix_auditorias_correlation_id", table_name="auditorias")
    op.drop_index("ix_auditorias_usuario_registrado_em", table_name="auditorias")
    op.drop_index("ix_auditorias_registrado_em", table_name="auditorias")
    op.alter_column("auditorias", "entidade_id", nullable=False)
    op.drop_column("auditorias", "motivo")
    op.drop_column("auditorias", "correlation_id")
    op.drop_constraint("ck_auditoria_autor_coerente", "auditorias", type_="check")
    op.drop_constraint("ck_auditoria_origem_valida", "auditorias", type_="check")
    op.drop_column("auditorias", "origem")

    op.drop_constraint("ck_auditoria_acao_valida", "auditorias", type_="check")
    for antiga, nova in TRADUCAO:
        op.execute(sa.text("UPDATE auditorias SET acao = :antiga WHERE acao = :nova")
                   .bindparams(nova=nova, antiga=antiga))
    op.create_check_constraint(
        "ck_auditoria_acao_valida", "auditorias", f"acao IN ({_lista(ACOES_ANTIGAS)})"
    )
