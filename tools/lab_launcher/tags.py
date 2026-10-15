"""Seleção manual das tags físicas e dos nomes de equipamento do ensaio."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import typer
from sqlalchemy import create_engine, text

from api.epc import normalizar_epc


@dataclass(frozen=True)
class EpcObservado:
    """Estrutura Epc Observado usada por tools.lab_launcher.tags.

    Campos: epc, leituras, ultima, equipamento."""
    epc: str
    leituras: int
    ultima: datetime
    equipamento: str | None


def parse_tag(valor: str) -> tuple[str, str]:
    """Converte ``EPC=Nome`` em par normalizado; usado por ``--tag``."""
    epc, separador, nome = valor.partition("=")
    if not separador or not nome.strip():
        raise ValueError(f"tag inválida {valor!r}: use --tag EPC=Nome do equipamento")
    return normalizar_epc(epc), nome.strip()


def epcs_recentes(database_url: str, horas: int = 24, limite: int = 20) -> list[EpcObservado]:
    """EPCs já gravados em ``leituras_brutas``, para ajudar a escolher as tags."""
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            linhas = conn.execute(text("""
                SELECT l.epc, COUNT(*) AS leituras, MAX(l.recebido_em) AS ultima,
                       (SELECT e.nome FROM tags t
                          JOIN associacoes_tag_equipamento a
                            ON a.tag_id = t.id AND a.fim IS NULL
                          JOIN equipamentos e ON e.id = a.equipamento_id
                         WHERE t.epc = l.epc LIMIT 1) AS equipamento
                  FROM leituras_brutas l
                 WHERE l.recebido_em >= now() - make_interval(hours => :horas)
                 GROUP BY l.epc
                 ORDER BY MAX(l.recebido_em) DESC
                 LIMIT :limite
            """), {"horas": horas, "limite": limite}).all()
    finally:
        engine.dispose()
    return [EpcObservado(*linha) for linha in linhas]


def perguntar_tags(recentes: list[EpcObservado]) -> list[tuple[str, str]]:
    """Pergunta EPC e nome até uma linha vazia; aceita o número da lista."""
    if recentes:
        typer.echo("EPCs lidos recentemente (últimas 24 h):")
        for indice, item in enumerate(recentes, start=1):
            vinculo = f" → {item.equipamento}" if item.equipamento else " (sem cadastro)"
            typer.echo(f"  {indice:2}. {item.epc}  {item.leituras} leitura(s), "
                       f"última {item.ultima:%d/%m %H:%M:%S}{vinculo}")
    else:
        typer.echo("Nenhuma leitura recente no banco; digite os EPCs das etiquetas.")
    typer.echo("Informe as tags do ensaio (número da lista ou EPC). "
               "Deixe vazio para concluir.")
    escolhidas: dict[str, str] = {}
    while True:
        entrada = typer.prompt("EPC", default="", show_default=False).strip()
        if not entrada:
            return list(escolhidas.items())
        sugestao = None
        if entrada.isdigit() and 1 <= int(entrada) <= len(recentes):
            item = recentes[int(entrada) - 1]
            entrada, sugestao = item.epc, item.equipamento
        try:
            epc = normalizar_epc(entrada)
        except ValueError as erro:
            typer.echo(f"  {erro}")
            continue
        nome = ""
        while not nome:
            nome = typer.prompt(f"Nome do equipamento para {epc}",
                                default=sugestao or escolhidas.get(epc) or "").strip()
        escolhidas[epc] = nome
