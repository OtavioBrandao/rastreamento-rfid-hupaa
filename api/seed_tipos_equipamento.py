"""
Seed idempotente dos tipos de equipamento básicos (ISS-009).

Uso:
    python -m api.seed_tipos_equipamento

Idempotência: a checagem de existência é feita por `nome_normalizado`, e
não por `nome` exato. Comparar por `nome` deixaria o seed "passar" e o
INSERT estourar no UNIQUE quando o banco já tivesse, por exemplo,
"Carrinho de Emergencia" (sem acento) — ou pior, criaria uma variação
duplicada se o UNIQUE ainda não existisse.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.database import SessionLocal
from api.normalizacao import normalizar_nome
from api.service_tipos_equipamento import criar
from db.models import TipoEquipamento

TIPOS_PADRAO: tuple[str, ...] = (
    "Maca",
    "Cadeira de rodas",
    "Carrinho de emergência",
)


def semear(session: Session) -> list[TipoEquipamento]:
    """Cria os tipos padrão que ainda não existem. Devolve só os criados agora."""
    criados: list[TipoEquipamento] = []
    for nome in TIPOS_PADRAO:
        normalizado = normalizar_nome(nome)
        ja_existe = session.scalar(
            select(TipoEquipamento).where(TipoEquipamento.nome_normalizado == normalizado)
        )
        if ja_existe is not None:
            continue
        criados.append(criar(session, nome=nome))
    return criados


def main() -> None:
    session = SessionLocal()
    try:
        # Os nomes são lidos AINDA com a sessão aberta: depois do
        # `close()` as instâncias ficam destacadas e qualquer atributo
        # que precise de recarga estoura DetachedInstanceError.
        nomes_criados = [tipo.nome for tipo in semear(session)]
    finally:
        session.close()

    for nome in nomes_criados:
        print(f"criado: {nome}")
    ja_existiam = len(TIPOS_PADRAO) - len(nomes_criados)
    print(f"seed concluído: {len(nomes_criados)} criado(s), {ja_existiam} já existia(m)")


if __name__ == "__main__":
    main()
