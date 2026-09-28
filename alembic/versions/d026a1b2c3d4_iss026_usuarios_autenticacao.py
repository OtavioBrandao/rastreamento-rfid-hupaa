"""ISS-026: perfis semeados, e-mail normalizado, estado de login e sessões."""

import sqlalchemy as sa
from alembic import op

revision = "d026a1b2c3d4"
down_revision = "c032b1a2d3e4"
branch_labels = None
depends_on = None


def _abortar_se_emails_colidirem(bind) -> None:
    """
    Roda ANTES de qualquer alteração: a normalização não pode fundir duas
    contas em silêncio. A mensagem lista só ids — e-mail é dado pessoal e
    não deve ir para log de deploy.
    """
    colisoes = bind.execute(sa.text(
        "SELECT array_agg(id ORDER BY id) FROM usuarios "
        "GROUP BY lower(btrim(email)) HAVING count(*) > 1 ORDER BY min(id)"
    )).scalars().all()
    if colisoes:
        grupos = "; ".join(", ".join(str(item) for item in ids) for ids in colisoes)
        raise RuntimeError(
            "ISS-026: normalizar usuarios.email faria contas colidirem "
            f"(ids por grupo: {grupos}). Resolva manualmente e rode de novo; "
            "nada foi alterado."
        )


def upgrade() -> None:
    bind = op.get_bind()
    # Impede um INSERT concorrente de criar colisão entre a checagem e o UPDATE.
    bind.execute(sa.text("LOCK TABLE usuarios IN SHARE ROW EXCLUSIVE MODE"))
    _abortar_se_emails_colidirem(bind)

    op.execute(
        "INSERT INTO perfis (nome) VALUES ('operacional'), ('administrador') "
        "ON CONFLICT (nome) DO NOTHING"
    )
    op.execute(
        "UPDATE usuarios SET email = lower(btrim(email)) WHERE email <> lower(btrim(email))"
    )
    op.create_check_constraint(
        "ck_usuarios_email_normalizado", "usuarios", "email = lower(btrim(email))"
    )

    op.add_column("usuarios", sa.Column(
        "deve_trocar_senha", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("usuarios", sa.Column(
        "tentativas_falhas", sa.Integer(), server_default="0", nullable=False))
    op.add_column("usuarios", sa.Column(
        "bloqueado_ate", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("usuarios", sa.Column(
        "ultimo_login_em", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("usuarios", sa.Column(
        "updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"),
        nullable=False))
    op.create_check_constraint(
        "ck_usuarios_tentativas_nao_negativas", "usuarios", "tentativas_falhas >= 0"
    )

    op.create_table(
        "sessoes",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("criada_em", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("expira_em", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("revogada_em", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("motivo_revogacao", sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], name="fk_sessoes_usuario_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_sessoes_token_hash"),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="ck_sessoes_token_hash_formato"),
        sa.CheckConstraint("expira_em > criada_em", name="ck_sessoes_expiracao_posterior"),
        sa.CheckConstraint(
            "(revogada_em IS NULL) = (motivo_revogacao IS NULL)",
            name="ck_sessoes_revogacao_consistente",
        ),
        sa.CheckConstraint(
            "motivo_revogacao IS NULL OR motivo_revogacao IN "
            "('logout', 'troca_senha', 'redefinicao_senha', 'desativacao')",
            name="ck_sessoes_motivo_valido",
        ),
    )
    op.create_index(
        "ix_sessoes_usuario_nao_revogadas", "sessoes", ["usuario_id"],
        postgresql_where=sa.text("revogada_em IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_sessoes_usuario_nao_revogadas", table_name="sessoes")
    op.drop_table("sessoes")
    op.drop_constraint("ck_usuarios_tentativas_nao_negativas", "usuarios", type_="check")
    for coluna in (
        "updated_at", "ultimo_login_em", "bloqueado_ate", "tentativas_falhas",
        "deve_trocar_senha",
    ):
        op.drop_column("usuarios", coluna)
    # Os e-mails continuam normalizados: a forma original não foi guardada.
    op.drop_constraint("ck_usuarios_email_normalizado", "usuarios", type_="check")
    op.execute(
        "DELETE FROM perfis p WHERE p.nome IN ('operacional', 'administrador') "
        "AND NOT EXISTS (SELECT 1 FROM usuarios u WHERE u.perfil_id = p.id)"
    )
