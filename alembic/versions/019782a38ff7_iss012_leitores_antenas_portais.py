"""iss-012: portal_id na antena, reader_id/ativo/parametros_ingestao no leitor, ativo em antenas/portais

Revision ID: 019782a38ff7
Revises: af6d99290414
Create Date: 2026-09-20

CRUD de leitores, antenas e portais (ISS-012).

Mudança estrutural: a associação portal <-> hardware passa a ser DIRETA na
antena (`antenas.portal_id`) e `leitores.portal_id` é REMOVIDA. Um leitor
pode ter antenas em portais diferentes, e um portal pode agregar antenas de
leitores diferentes — coisa que `leitores.portal_id` (1 leitor -> 1 portal)
não conseguia representar.

Ordem do upgrade (importa — mesmo padrão nullable-first + backfill das
ISS-008/009/011):

1. colunas novas entram NULLABLE (as NOT NULL com default entram direto);
2. `leitores.reader_id` é preenchido com `identificador_serial` (o único valor
   já existente e já único que serve de ponto de partida; os dois campos
   passam a ser independentes daí em diante);
3. o `portal_id` de cada leitor é REPLICADO para todas as antenas dele — só
   depois `leitores.portal_id` é derrubada. Sem isso a informação de onde o
   leitor está instalado se perderia em silêncio;
4. só então `reader_id` vira NOT NULL + UNIQUE nomeada.

Onde a informação NÃO tem para onde ir a migration ABORTA em vez de perder
dado em silêncio: leitor com `portal_id` mas SEM nenhuma antena (não há linha
que carregue o portal). Resolva cadastrando ao menos uma antena para ele ou
limpando `leitores.portal_id`, e rode de novo.

Downgrade: restaura `leitores.portal_id` a partir das antenas quando não há
ambiguidade. Um leitor com antenas em portais DIFERENTES não cabe no modelo
antigo (1 leitor -> 1 portal): o downgrade aborta listando-os. Os valores de
`reader_id` que já divergiam de `identificador_serial` e `parametros_ingestao`
se perdem no downgrade (as colunas deixam de existir) — inerente a reverter.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '019782a38ff7'
down_revision: Union[str, Sequence[str], None] = 'af6d99290414'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UNIQUE_READER_ID = "uq_leitores_reader_id"
FK_ANTENA_PORTAL = "fk_antenas_portal_id"
INDICE_ANTENA_PORTAL = "ix_antenas_portal_id"


def _ativo_column() -> sa.Column:
    return sa.Column("ativo", sa.Boolean(), server_default=sa.text("true"), nullable=False)


def _exigir_que_nenhum_leitor_com_portal_fique_sem_antena(conexao) -> None:
    orfaos = conexao.execute(
        sa.text(
            "SELECT l.id, l.identificador_serial, l.portal_id FROM leitores l "
            "WHERE l.portal_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM antenas a WHERE a.leitor_id = l.id) "
            "ORDER BY l.id"
        )
    ).fetchall()
    if orfaos:
        detalhe = "; ".join(
            f"leitor {o.id} (serial {o.identificador_serial!r}) -> portal {o.portal_id}"
            for o in orfaos
        )
        raise RuntimeError(
            "leitores.portal_id está preenchido em leitor(es) SEM nenhuma antena; a "
            "associação portal<->leitor passa a morar na antena e, sem antena, ela se "
            "perderia em silêncio. Cadastre ao menos uma antena para cada um (ela herda "
            "o portal) ou limpe leitores.portal_id, e rode a migration de novo. "
            f"Afetados: {detalhe}"
        )


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("leitores", sa.Column("reader_id", sa.String(), nullable=True))
    op.add_column("leitores", sa.Column("parametros_ingestao", postgresql.JSONB(), nullable=True))
    op.add_column("leitores", _ativo_column())
    op.add_column("antenas", sa.Column("portal_id", sa.BigInteger(), nullable=True))
    op.add_column("antenas", _ativo_column())
    op.add_column("portais", _ativo_column())

    conexao = op.get_bind()

    # identificador_serial já é UNIQUE, então reader_id nasce sem colisão.
    conexao.execute(sa.text("UPDATE leitores SET reader_id = identificador_serial"))

    _exigir_que_nenhum_leitor_com_portal_fique_sem_antena(conexao)
    conexao.execute(
        sa.text(
            "UPDATE antenas a SET portal_id = l.portal_id "
            "FROM leitores l WHERE a.leitor_id = l.id AND l.portal_id IS NOT NULL"
        )
    )

    op.alter_column("leitores", "reader_id", nullable=False)
    # Nomes explícitos: o autogenerate cria constraint anônima, e sem nome o
    # downgrade não consegue derrubá-la de forma determinística.
    op.create_unique_constraint(UNIQUE_READER_ID, "leitores", ["reader_id"])
    op.create_foreign_key(FK_ANTENA_PORTAL, "antenas", "portais", ["portal_id"], ["id"])
    op.create_index(INDICE_ANTENA_PORTAL, "antenas", ["portal_id"], unique=False)

    # Já replicado para as antenas: agora sim a coluna antiga pode cair (a FK
    # dela, `leitores_portal_id_fkey`, cai junto).
    op.drop_column("leitores", "portal_id")


def downgrade() -> None:
    """Downgrade schema."""
    conexao = op.get_bind()

    ambiguos = conexao.execute(
        sa.text(
            "SELECT leitor_id, array_agg(DISTINCT portal_id ORDER BY portal_id) AS portais "
            "FROM antenas WHERE portal_id IS NOT NULL "
            "GROUP BY leitor_id HAVING COUNT(DISTINCT portal_id) > 1 ORDER BY leitor_id"
        )
    ).fetchall()
    if ambiguos:
        detalhe = "; ".join(f"leitor {a.leitor_id} -> portais {list(a.portais)}" for a in ambiguos)
        raise RuntimeError(
            "leitor(es) com antenas em portais DIFERENTES não cabem no modelo antigo "
            "(leitores.portal_id: 1 leitor -> 1 portal); reverter perderia essa "
            "informação em silêncio. Reagrupe as antenas (mesmo portal por leitor) e rode "
            f"o downgrade de novo. Afetados: {detalhe}"
        )

    op.add_column(
        "leitores",
        sa.Column("portal_id", sa.BigInteger(), sa.ForeignKey("portais.id"), nullable=True),
    )
    conexao.execute(
        sa.text(
            "UPDATE leitores l SET portal_id = s.portal_id FROM ("
            "SELECT leitor_id, MIN(portal_id) AS portal_id FROM antenas "
            "WHERE portal_id IS NOT NULL GROUP BY leitor_id) s WHERE l.id = s.leitor_id"
        )
    )

    op.drop_index(INDICE_ANTENA_PORTAL, table_name="antenas")
    op.drop_constraint(FK_ANTENA_PORTAL, "antenas", type_="foreignkey")
    op.drop_column("antenas", "portal_id")
    op.drop_column("antenas", "ativo")
    op.drop_column("portais", "ativo")
    op.drop_constraint(UNIQUE_READER_ID, "leitores", type_="unique")
    op.drop_column("leitores", "ativo")
    op.drop_column("leitores", "parametros_ingestao")
    op.drop_column("leitores", "reader_id")
