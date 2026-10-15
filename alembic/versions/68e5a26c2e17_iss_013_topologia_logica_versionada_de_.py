"""iss-013: topologia logica versionada de portais

Revision ID: 68e5a26c2e17
Revises: da436f7c75b3
Create Date: 2026-09-21 20:42:50.687555

Cria a tabela `mapeamentos_antena_portal` para modelagem temporal versionada
da topologia logica de portais (ISS-013), estabelecendo o significado de cada
antena no ponto de controle (lado A/B, zona e funcao operacional).

Preserva o historico atraves de intervalos semiabertos [inicio, fim).
Garante unicidade de no maximo um mapeamento ativo por antena fisica atraves
do indice unico parcial `uq_mapeamento_antena_ativo` (WHERE fim IS NULL).

Executa backfill seguro de antenas ativas associadas a portais existentes,
com validacao fail-fast caso haja inconsistencias de zona ou funcao indefinida.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '68e5a26c2e17'
down_revision: Union[str, Sequence[str], None] = 'da436f7c75b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Aplica a revisão: iss-013: topologia logica versionada de portais."""
    op.create_table(
        'mapeamentos_antena_portal',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column(
            'antena_id',
            sa.BigInteger(),
            sa.ForeignKey('antenas.id', name='fk_mapeamentos_antena_id'),
            nullable=False,
        ),
        sa.Column(
            'portal_id',
            sa.BigInteger(),
            sa.ForeignKey('portais.id', name='fk_mapeamentos_portal_id'),
            nullable=False,
        ),
        sa.Column('lado', sa.String(1), nullable=False),
        sa.Column(
            'zona_id',
            sa.BigInteger(),
            sa.ForeignKey('zonas.id', name='fk_mapeamentos_zona_id'),
            nullable=False,
        ),
        sa.Column('funcao', sa.String(20), nullable=False),
        sa.Column(
            'inicio',
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('fim', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.CheckConstraint("lado IN ('a', 'b')", name='ck_mapeamento_lado_valido'),
        sa.CheckConstraint(
            "funcao IN ('entrada', 'saida', 'auxiliar')",
            name='ck_mapeamento_funcao_valida',
        ),
        sa.CheckConstraint(
            'fim IS NULL OR fim >= inicio',
            name='ck_mapeamento_periodo_valido',
        ),
    )

    op.create_index(
        'uq_mapeamento_antena_ativo',
        'mapeamentos_antena_portal',
        ['antena_id'],
        unique=True,
        postgresql_where=sa.text('fim IS NULL'),
    )
    op.create_index(
        'ix_mapeamentos_portal_id',
        'mapeamentos_antena_portal',
        ['portal_id'],
    )
    op.create_index(
        'ix_mapeamentos_antena_id',
        'mapeamentos_antena_portal',
        ['antena_id'],
    )
    op.create_index(
        'ix_mapeamentos_zona_id',
        'mapeamentos_antena_portal',
        ['zona_id'],
    )

    # Backfill safe derivation for existing antennas associated with a portal
    conn = op.get_bind()
    query = sa.text("""
        SELECT a.id, a.portal_id, a.zona_associada_id, a.funcao, a.ativo,
               p.zona_a_id, p.zona_b_id
        FROM antenas a
        JOIN portais p ON p.id = a.portal_id
        WHERE a.portal_id IS NOT NULL
        ORDER BY a.id
    """)
    rows = conn.execute(query).fetchall()
    for row in rows:
        antena_id, portal_id, zona_associada_id, funcao, ativo, zona_a_id, zona_b_id = row

        # Determine logical side
        if zona_associada_id == zona_a_id:
            lado = 'a'
        elif zona_associada_id == zona_b_id:
            lado = 'b'
        else:
            raise RuntimeError(
                f"Falha na migracao ISS-013: Antena id={antena_id} associada ao portal id={portal_id} "
                f"possui zona_associada_id={zona_associada_id}, que nao corresponde nem a zona_a_id={zona_a_id} "
                f"nem a zona_b_id={zona_b_id} do portal. Inconsistencia deve ser resolvida antes da migracao."
            )

        # Validate operational function
        if funcao not in ('entrada', 'saida', 'auxiliar'):
            raise RuntimeError(
                f"Falha na migracao ISS-013: Antena id={antena_id} associada ao portal id={portal_id} "
                f"possui funcao='{funcao}', que e incompativel com o contrato de mapeamento logico "
                "('entrada', 'saida', 'auxiliar'). A funcao nao pode ser 'indefinido' para um mapeamento ativo."
            )

        # Only active antennas receive an active logical mapping
        if ativo:
            conn.execute(
                sa.text("""
                    INSERT INTO mapeamentos_antena_portal (
                        antena_id, portal_id, lado, zona_id, funcao, inicio, fim, created_at
                    ) VALUES (
                        :antena_id, :portal_id, :lado, :zona_id, :funcao, now(), NULL, now()
                    )
                """),
                {
                    "antena_id": antena_id,
                    "portal_id": portal_id,
                    "lado": lado,
                    "zona_id": zona_associada_id,
                    "funcao": funcao,
                },
            )


def downgrade() -> None:
    """Reverte a revisão: iss-013: topologia logica versionada de portais."""
    op.drop_index('ix_mapeamentos_zona_id', table_name='mapeamentos_antena_portal')
    op.drop_index('ix_mapeamentos_antena_id', table_name='mapeamentos_antena_portal')
    op.drop_index('ix_mapeamentos_portal_id', table_name='mapeamentos_antena_portal')
    op.drop_index('uq_mapeamento_antena_ativo', table_name='mapeamentos_antena_portal')
    op.drop_table('mapeamentos_antena_portal')
