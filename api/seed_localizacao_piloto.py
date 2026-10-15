"""
Seed idempotente e configurável do setor piloto do 4º andar (ISS-011).

Uso:
    python -m api.seed_localizacao_piloto
    python -m api.seed_localizacao_piloto --andar "4º Andar" --setor "Ala Norte" \\
        --zona "Corredor" --zona "Posto de Enfermagem"

Os nomes DEFAULT de `ConfigLocalizacaoPiloto` são PLACEHOLDERS: a
nomenclatura oficial do hospital ainda é uma pergunta em aberto
(`docs/architecture/data-model.md`, "Nomenclatura oficial de
andares/setores"). Por isso a config é sobrescrevível — pela dataclass, em
código, ou pela linha de comando.

Idempotência em CADA nível (acha-ou-cria andar, depois setor dentro do
andar, depois cada zona dentro do setor), sempre por `nome_normalizado` e
dentro do escopo certo — não por `nome` exato, senão "4o andar" (sem
acento) não seria reconhecido como o "4º Andar" que já existe e o INSERT
estouraria no UNIQUE.

Um andar/setor que já existe é REUTILIZADO como está, mesmo inativo — o
seed nunca reativa nada sozinho. Se o andar existir inativo e o setor ainda
não, criar o setor falha com `PaiInvalido` (o serviço não cria filho sob
pai inativo): reative o andar de propósito e rode de novo.
"""

import argparse
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.database import SessionLocal
from api.normalizacao import normalizar_nome
from api.service_localizacao import ErroLocalizacao, criar_andar, criar_setor, criar_zona
from db.models import Andar, Setor, Zona


@dataclass(frozen=True)
class ConfigLocalizacaoPiloto:
    """Nomes do setor piloto. Os defaults são placeholders — ver docstring do módulo."""

    andar: str = "4º Andar"
    setor: str = "Ala Norte"
    zonas: tuple[str, ...] = ("Corredor", "Posto de Enfermagem", "Enfermaria 01")

    def __post_init__(self) -> None:
        """Valida as invariantes dos campos após a construção da estrutura."""
        for rotulo, valor in (("andar", self.andar), ("setor", self.setor)):
            if not valor.strip():
                raise ValueError(f"{rotulo} não pode ser vazio")
        if not self.zonas:
            raise ValueError("informe ao menos uma zona")
        if any(not zona.strip() for zona in self.zonas):
            raise ValueError("nome de zona não pode ser vazio")


@dataclass
class ResultadoSeed:
    """Só o que foi CRIADO nesta execução (primitivos: seguros depois de fechar a sessão)."""

    andar_criado: bool = False
    setor_criado: bool = False
    zonas_criadas: list[str] = field(default_factory=list)

    @property
    def total_criado(self) -> int:
        """Soma as entidades criadas pelo seed nesta execução."""
        return int(self.andar_criado) + int(self.setor_criado) + len(self.zonas_criadas)


def semear(session: Session, config: ConfigLocalizacaoPiloto | None = None) -> ResultadoSeed:
    """Cria ou reutiliza o cadastro base do cenário, preservando identificadores e regras de integridade."""
    config = config or ConfigLocalizacaoPiloto()
    resultado = ResultadoSeed()

    andar = session.scalar(
        select(Andar).where(Andar.nome_normalizado == normalizar_nome(config.andar))
    )
    if andar is None:
        andar = criar_andar(session, nome=config.andar)
        resultado.andar_criado = True

    setor = session.scalar(
        select(Setor).where(
            Setor.andar_id == andar.id,
            Setor.nome_normalizado == normalizar_nome(config.setor),
        )
    )
    if setor is None:
        setor = criar_setor(session, andar_id=andar.id, nome=config.setor)
        resultado.setor_criado = True

    for nome_zona in config.zonas:
        existente = session.scalar(
            select(Zona).where(
                Zona.setor_id == setor.id,
                Zona.nome_normalizado == normalizar_nome(nome_zona),
            )
        )
        if existente is None:
            criar_zona(session, setor_id=setor.id, nome=nome_zona)
            resultado.zonas_criadas.append(nome_zona)

    return resultado


def _config_da_linha_de_comando(argv: list[str] | None) -> ConfigLocalizacaoPiloto:
    """Constrói configuração do seed piloto a partir dos argumentos da CLI."""
    padrao = ConfigLocalizacaoPiloto()
    parser = argparse.ArgumentParser(description="Seed do setor piloto do 4º andar (ISS-011).")
    parser.add_argument("--andar", default=padrao.andar, help="nome do andar")
    parser.add_argument("--setor", default=padrao.setor, help="nome do setor")
    parser.add_argument(
        "--zona",
        action="append",
        dest="zonas",
        help="nome de uma zona (repita a opção para várias); substitui as zonas default",
    )
    args = parser.parse_args(argv)
    return ConfigLocalizacaoPiloto(
        andar=args.andar,
        setor=args.setor,
        zonas=tuple(args.zonas) if args.zonas else padrao.zonas,
    )


def main(argv: list[str] | None = None) -> int:
    """Executa a entrada de linha de comando de api.seed_localizacao_piloto; devolve o código de saída quando aplicável."""
    config = _config_da_linha_de_comando(argv)
    session = SessionLocal()
    try:
        resultado = semear(session, config)
    except ErroLocalizacao as erro:
        print(f"seed abortado: {erro}")
        return 1
    finally:
        session.close()

    if resultado.andar_criado:
        print(f"criado: andar {config.andar!r}")
    if resultado.setor_criado:
        print(f"criado: setor {config.setor!r}")
    for nome in resultado.zonas_criadas:
        print(f"criado: zona {nome!r}")
    print(f"seed concluído: {resultado.total_criado} criado(s); o resto já existia")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
