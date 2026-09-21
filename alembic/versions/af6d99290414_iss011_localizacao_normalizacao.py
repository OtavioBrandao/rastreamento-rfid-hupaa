"""iss-011: nome_normalizado, descricao, referencia_planta, ativo e timestamps em andares/setores/zonas

Revision ID: af6d99290414
Revises: 992c5c770214
Create Date: 2026-09-19

CRUD da hierarquia física andar -> setor -> zona (RF-004).

Mesmo padrão nullable-first + backfill das migrations da ISS-009 e ISS-008:
`nome_normalizado` nasce NULLABLE, as linhas já existentes são preenchidas
por backfill, e só então a coluna vira NOT NULL + UNIQUE nomeada, no escopo
certo de cada nível:

- andares: único globalmente
- setores: único dentro do andar   (andar_id, nome_normalizado)
- zonas:   único dentro do setor   (setor_id, nome_normalizado)

`zonas.observacoes` (zona morta) NÃO é tocada: é semanticamente diferente
de `descricao`, que é adicionada ao lado dela.

As UNIQUE antigas sobre `nome` exato (`andares_nome_key`,
`uq_setor_nome_por_andar`, `uq_zona_nome_por_setor`) continuam como estão —
são mais frouxas que as novas, então não conflitam.
"""
import re
import unicodedata
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'af6d99290414'
down_revision: Union[str, Sequence[str], None] = '992c5c770214'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ESPACOS_REPETIDOS = re.compile(r"\s+")

# (tabela, coluna de escopo da unicidade ou None se global, nome da UNIQUE nova)
NIVEIS = (
    ("andares", None, "uq_andares_nome_normalizado"),
    ("setores", "andar_id", "uq_setor_nome_normalizado_por_andar"),
    ("zonas", "setor_id", "uq_zona_nome_normalizado_por_setor"),
)


def _normalizar(valor: str) -> str:
    """
    CÓPIA INLINE, DE PROPÓSITO, de `api.normalizacao.normalizar_nome`.

    Uma migration não pode importar código de aplicação: precisa produzir
    o MESMO resultado daqui a um ano, mesmo que a função da aplicação
    mude. Regra nova = migration nova que recalcule o backfill, nunca
    edição desta.
    """
    sem_acento = unicodedata.normalize("NFKD", valor).encode("ascii", "ignore").decode("ascii")
    return _ESPACOS_REPETIDOS.sub(" ", sem_acento.strip()).lower()


def _backfill(conexao, tabela: str, coluna_escopo: str | None) -> None:
    """
    Preenche `nome_normalizado` de uma tabela antes de a coluna virar
    NOT NULL + UNIQUE.

    Colisão é checada NO ESCOPO da UNIQUE nova (mesmo andar, mesmo setor, ou
    global): "Enfermaria" em dois andares diferentes NÃO é colisão. Se houver
    colisão real, a migration aborta listando os conflitos em vez de decidir
    sozinha quem sobrevive — mesma política da ISS-009/ISS-008.
    """
    colunas = f"id, nome{', ' + coluna_escopo if coluna_escopo else ''}"
    linhas = conexao.execute(sa.text(f"SELECT {colunas} FROM {tabela} ORDER BY id")).fetchall()

    grupos: dict[tuple, list[str]] = {}
    for linha in linhas:
        escopo = getattr(linha, coluna_escopo) if coluna_escopo else None
        grupos.setdefault((escopo, _normalizar(linha.nome)), []).append(linha.nome)

    conflitos = {chave: nomes for chave, nomes in grupos.items() if len(nomes) > 1}
    if conflitos:
        detalhe = "; ".join(
            f"[{coluna_escopo}={escopo}] {normalizado!r} <- {nomes}"
            if coluna_escopo
            else f"{normalizado!r} <- {nomes}"
            for (escopo, normalizado), nomes in sorted(conflitos.items(), key=str)
        )
        raise RuntimeError(
            f"{tabela} tem nomes que colidem após a normalização da ISS-011. "
            "Resolva manualmente (renomeie ou remova os duplicados) e rode a "
            f"migration de novo. Conflitos: {detalhe}"
        )

    for linha in linhas:
        conexao.execute(
            sa.text(f"UPDATE {tabela} SET nome_normalizado = :normalizado WHERE id = :id"),
            {"normalizado": _normalizar(linha.nome), "id": linha.id},
        )


def upgrade() -> None:
    """Upgrade schema."""
    for tabela, _, _ in NIVEIS:
        op.add_column(tabela, sa.Column("nome_normalizado", sa.String(), nullable=True))
        op.add_column(tabela, sa.Column("descricao", sa.Text(), nullable=True))
        op.add_column(tabela, sa.Column("referencia_planta", sa.String(), nullable=True))
        op.add_column(
            tabela,
            sa.Column("ativo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        )
        op.add_column(
            tabela,
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.add_column(
            tabela,
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )

    conexao = op.get_bind()
    for tabela, coluna_escopo, _ in NIVEIS:
        _backfill(conexao, tabela, coluna_escopo)

    for tabela, coluna_escopo, nome_unique in NIVEIS:
        op.alter_column(tabela, "nome_normalizado", nullable=False)
        # Nome explícito: o autogenerate cria constraint anônima, e sem nome
        # o downgrade não consegue derrubá-la de forma determinística.
        colunas = [coluna_escopo, "nome_normalizado"] if coluna_escopo else ["nome_normalizado"]
        op.create_unique_constraint(nome_unique, tabela, colunas)


def downgrade() -> None:
    """Downgrade schema."""
    for tabela, _, nome_unique in reversed(NIVEIS):
        op.drop_constraint(nome_unique, tabela, type_="unique")
        op.drop_column(tabela, "updated_at")
        op.drop_column(tabela, "created_at")
        op.drop_column(tabela, "ativo")
        op.drop_column(tabela, "referencia_planta")
        op.drop_column(tabela, "descricao")
        op.drop_column(tabela, "nome_normalizado")
