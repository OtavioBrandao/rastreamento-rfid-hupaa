"""Cadastro mínimo e idempotente para o portal de laboratório."""

from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.database import SessionLocal
from api.normalizacao import normalizar_nome
from api.seed_localizacao_piloto import ConfigLocalizacaoPiloto
from api.seed_localizacao_piloto import semear as semear_zonas
from api.service_hardware import criar_antena, criar_leitor, criar_portal
from api.service_topologia_portal import criar_mapeamento
from db.models import Andar, Antena, Leitor, MapeamentoAntenaPortal, Portal, Setor, Zona
from rfid_ingestion.topics import reading_topic

ANDAR = "Laboratório RFID"
SETOR = "Bancada de testes"
ZONAS = ("Zona A", "Zona B")
PORTAL = "Portal de teste RFID"


def semear(session: Session, reader_id: str = "reader-01", serial: str | None = None) -> dict[str, str]:
    """Completa somente registros ausentes; divergências exigem correção explícita."""
    reading_topic(reader_id)
    semear_zonas(session, ConfigLocalizacaoPiloto(ANDAR, SETOR, ZONAS))
    setor = session.scalar(
        select(Setor).join(Andar).where(
            Andar.nome_normalizado == normalizar_nome(ANDAR),
            Setor.nome_normalizado == normalizar_nome(SETOR),
        )
    )
    zonas = {
        nome: session.scalar(
            select(Zona).where(
                Zona.setor_id == setor.id, Zona.nome_normalizado == normalizar_nome(nome)
            )
        )
        for nome in ZONAS
    }
    if not setor.ativo or any(not zona.ativo for zona in zonas.values()):
        raise ValueError("setor ou zona de laboratório inativo")

    resumo = {"zonas": "conferidas", "leitor": "reutilizado", "portal": "reutilizado"}
    leitor = session.scalar(select(Leitor).where(Leitor.reader_id == reader_id))
    if leitor is None:
        leitor = criar_leitor(
            session, reader_id, "Identix", "EZ700", serial or f"LAB-{reader_id}"
        )
        resumo["leitor"] = "criado"
    elif not leitor.ativo or (serial and leitor.identificador_serial != serial):
        raise ValueError("leitor existente inativo ou com serial divergente")

    portal = session.scalar(select(Portal).where(Portal.nome == PORTAL))
    if portal is None:
        portal = criar_portal(session, PORTAL, zonas["Zona A"].id, zonas["Zona B"].id)
        resumo["portal"] = "criado"
    elif (
        not portal.ativo
        or portal.zona_a_id != zonas["Zona A"].id
        or portal.zona_b_id != zonas["Zona B"].id
    ):
        raise ValueError("portal de laboratório existente com topologia divergente")

    for porta, lado, funcao, nome_zona in (
        (1, "a", "entrada", "Zona A"),
        (2, "b", "saida", "Zona B"),
    ):
        zona = zonas[nome_zona]
        antena = session.scalar(
            select(Antena).where(
                Antena.leitor_id == leitor.id,
                Antena.porta_numero == porta,
                Antena.ativo.is_(True),
            )
        )
        if antena is None:
            antena = criar_antena(session, leitor.id, porta, zona.id, funcao, portal.id)
            resumo[f"antena {porta}"] = "criada"
        elif antena.portal_id != portal.id or antena.zona_associada_id != zona.id:
            raise ValueError(f"antena ativa da porta {porta} tem topologia divergente")
        else:
            resumo[f"antena {porta}"] = "reutilizada"
        mapping = session.scalar(
            select(MapeamentoAntenaPortal).where(
                MapeamentoAntenaPortal.antena_id == antena.id,
                MapeamentoAntenaPortal.fim.is_(None),
            )
        )
        if mapping is None:
            criar_mapeamento(session, portal.id, antena.id, lado, funcao, zona.id)
            resumo[f"mapeamento {porta}"] = "criado"
        elif (
            mapping.portal_id != portal.id
            or mapping.lado != lado
            or mapping.zona_id != zona.id
            or mapping.funcao != funcao
        ):
            raise ValueError(f"mapeamento ativo da porta {porta} diverge do laboratório")
        else:
            resumo[f"mapeamento {porta}"] = "reutilizado"
    return resumo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reader-id", default="reader-01")
    parser.add_argument("--serial")
    args = parser.parse_args()
    with SessionLocal() as session:
        resumo = semear(session, args.reader_id, args.serial)
    print("Cadastro base: " + "; ".join(f"{chave}: {estado}"
                                        for chave, estado in resumo.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
