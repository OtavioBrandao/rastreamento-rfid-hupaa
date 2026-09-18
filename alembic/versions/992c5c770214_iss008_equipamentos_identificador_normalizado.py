"""iss-008: identificador_interno_normalizado, descricao e CHECK de status em equipamentos

Revision ID: 992c5c770214
Revises: 7c1d4e9a2b83
Create Date: 2026-09-18

CRUD de equipamentos (ISS-008), que depende da ISS-009
(`tipos_equipamento.ativo`) para validar `tipo_id` na criação/atualização.

Mesmo padrão de backfill da ISS-009: `identificador_interno_normalizado`
nasce NULLABLE, as linhas já existentes são preenchidas, e só então a
coluna vira NOT NULL + UNIQUE nomeada.

A CHECK de `status` não é detectada pelo autogenerate do Alembic — foi
escrita manualmente aqui a partir da modelagem (`db/models.py`), não
gerada.
"""
import re
import unicodedata
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '992c5c770214'
down_revision: Union[str, Sequence[str], None] = '7c1d4e9a2b83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UNIQUE_IDENTIFICADOR_NORMALIZADO = "uq_equipamentos_identificador_interno_normalizado"
CHECK_STATUS_VALIDO = "ck_equipamento_status_valido"

_ESPACOS_REPETIDOS = re.compile(r"\s+")


def _normalizar(valor: str) -> str:
    """
    CÓPIA INLINE, DE PROPÓSITO, de `api.normalizacao.normalizar_nome`.

    Mesmo motivo da migration da ISS-009: uma migration não pode importar
    código de aplicação — precisa continuar produzindo o MESMO resultado
    mesmo que a função da aplicação mude depois. Regra nova = migration
    nova que recalcule o backfill, nunca edição desta.
    """
    sem_acento = unicodedata.normalize("NFKD", valor).encode("ascii", "ignore").decode("ascii")
    return _ESPACOS_REPETIDOS.sub(" ", sem_acento.strip()).lower()


def _backfill_identificador_normalizado(conexao) -> None:
    """
    Preenche `identificador_interno_normalizado` das linhas já existentes
    antes de a coluna virar NOT NULL + UNIQUE.

    Mesma lógica de proteção contra colisão da ISS-009: se duas linhas
    pré-existentes colapsarem no mesmo valor normalizado, a migration
    aborta com a lista de conflitos em vez de decidir sozinha qual
    sobrevive.
    """
    linhas = conexao.execute(
        sa.text("SELECT id, identificador_interno FROM equipamentos ORDER BY id")
    ).fetchall()

    normalizados: dict[str, list[str]] = {}
    for linha in linhas:
        normalizados.setdefault(_normalizar(linha.identificador_interno), []).append(
            linha.identificador_interno
        )

    conflitos = {valor: nomes for valor, nomes in normalizados.items() if len(nomes) > 1}
    if conflitos:
        detalhe = "; ".join(
            f"{valor!r} <- {nomes}" for valor, nomes in sorted(conflitos.items())
        )
        raise RuntimeError(
            "equipamentos tem identificador_interno que colidem após a "
            "normalização da ISS-008. Resolva manualmente (renomeie ou remova "
            f"os duplicados) e rode a migration de novo. Conflitos: {detalhe}"
        )

    for linha in linhas:
        conexao.execute(
            sa.text(
                "UPDATE equipamentos SET identificador_interno_normalizado = :normalizado "
                "WHERE id = :id"
            ),
            {"normalizado": _normalizar(linha.identificador_interno), "id": linha.id},
        )


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "equipamentos",
        sa.Column("identificador_interno_normalizado", sa.String(), nullable=True),
    )
    op.add_column(
        "equipamentos",
        sa.Column("descricao", sa.Text(), nullable=True),
    )

    _backfill_identificador_normalizado(op.get_bind())

    op.alter_column("equipamentos", "identificador_interno_normalizado", nullable=False)
    # Nome explícito: `unique=True` do autogenerate cria constraint anônima,
    # e sem nome o downgrade não consegue derrubá-la de forma determinística.
    op.create_unique_constraint(
        UNIQUE_IDENTIFICADOR_NORMALIZADO, "equipamentos", ["identificador_interno_normalizado"]
    )
    # Autogenerate não detecta CHECK constraint — precisa ser escrita à mão.
    op.create_check_constraint(
        CHECK_STATUS_VALIDO, "equipamentos", "status IN ('ativo', 'inativo')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(CHECK_STATUS_VALIDO, "equipamentos", type_="check")
    op.drop_constraint(UNIQUE_IDENTIFICADOR_NORMALIZADO, "equipamentos", type_="unique")
    op.drop_column("equipamentos", "descricao")
    op.drop_column("equipamentos", "identificador_interno_normalizado")
