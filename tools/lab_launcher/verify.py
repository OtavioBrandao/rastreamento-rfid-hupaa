"""Confere o percurso sintético até passagem, movimento e última zona."""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import create_engine, text

from .synthetic import LeituraPlanejada


@dataclass(frozen=True)
class Baseline:
    leitura_id: int
    passagem_id: int


def inicio(database_url: str) -> Baseline:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            return Baseline(
                conn.scalar(text("SELECT COALESCE(MAX(id), 0) FROM leituras_brutas")),
                conn.scalar(text("SELECT COALESCE(MAX(id), 0) FROM passagens")),
            )
    finally:
        engine.dispose()


def conferir(database_url: str, baseline: Baseline, epcs: list[str], *,
             passagem: bool, mensagens: int, timeout: float = 30,
             contador_inicial: int | None = None,
             programa: tuple[LeituraPlanejada, ...] | None = None) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    pendentes = set(epc.upper() for epc in epcs)
    ultimo_estado: dict[str, str] = {}
    leituras_vistas = dict.fromkeys(pendentes, 0)
    ultimo_id_global = baseline.leitura_id
    esperados = {epc.upper(): mensagens for epc in epcs}
    direcoes: dict[str, list[str]] = {epc.upper(): [] for epc in epcs}
    if programa:
        esperados = dict.fromkeys(esperados, 0)
        porta_anterior: dict[str, int] = {}
        for leitura in programa:
            epc = leitura.epc.upper()
            esperados[epc] += 1
            anterior = porta_anterior.get(epc)
            if anterior is not None and anterior != leitura.porta:
                direcoes[epc].append("a_para_b" if anterior == 1 else "b_para_a")
            porta_anterior[epc] = leitura.porta
    total_esperado = sum(esperados.values())
    parametros_contador = {}
    filtro_leituras = ""
    joins_passagem = ""
    filtro_passagem = ""
    if contador_inicial is not None:
        # O contador original fica na auditoria JSONB. Todas as strings deste
        # ensaio têm sete dígitos; BETWEEN textual preserva a ordem numérica.
        parametros_contador = {
            "contador_inicio": str(contador_inicial),
            "contador_fim": str(contador_inicial + total_esperado - 1),
        }
        filtro_leituras = (
            " AND (dados_origem #>> '{metadata,timestamp_original}') "
            "BETWEEN :contador_inicio AND :contador_fim"
        )
        joins_passagem = (
            " JOIN leituras_brutas origem ON origem.id = p.leitura_origem_id"
            " JOIN leituras_brutas destino ON destino.id = p.leitura_destino_id"
        )
        filtro_passagem = (
            " AND (origem.dados_origem #>> '{metadata,timestamp_original}') "
            "BETWEEN :contador_inicio AND :contador_fim"
            " AND (destino.dados_origem #>> '{metadata,timestamp_original}') "
            "BETWEEN :contador_inicio AND :contador_fim"
        )
    consulta_leituras = text(
        "SELECT COUNT(*) FROM leituras_brutas "
        "WHERE id > :inicio AND epc = :epc" + filtro_leituras
    )
    consulta_passagem = text(
        "SELECT p.id, p.direcao_status, p.direcao, p.zona_destino_id "
        "FROM passagens p" + joins_passagem +
        " WHERE p.id > :inicio AND p.epc = :epc" + filtro_passagem +
        " ORDER BY p.id DESC LIMIT 1"
    )
    consulta_passagens = text(
        "SELECT p.id, p.direcao_status, p.direcao, p.zona_destino_id "
        "FROM passagens p" + joins_passagem +
        " WHERE p.id > :inicio AND p.epc = :epc" + filtro_passagem +
        " ORDER BY p.id"
    )
    # O Neon pode processar a fila MQTT mais devagar que a publicação. Aguardar
    # enquanto houver avanço, com limite total proporcional ao tamanho do ensaio.
    inicio_espera = time.monotonic()
    limite_total = 5 * total_esperado + timeout
    fim_total = inicio_espera + limite_total
    fim_sem_progresso = inicio_espera + timeout
    print(f"Aguardando até {limite_total:g}s pela ingestão; falha após "
          f"{timeout:g}s sem progresso...", flush=True)
    try:
        while pendentes and time.monotonic() < fim_total and time.monotonic() < fim_sem_progresso:
            progresso_atual = False
            with engine.connect() as conn:
                for epc in tuple(pendentes):
                    parametros = {"inicio": baseline.leitura_id, "epc": epc,
                                  **parametros_contador}
                    leituras = conn.scalar(consulta_leituras, parametros)
                    if leituras > leituras_vistas[epc]:
                        leituras_vistas[epc] = leituras
                        progresso_atual = True
                        fim_sem_progresso = time.monotonic() + timeout
                    esperado = esperados[epc]
                    if leituras < esperado:
                        estado = f"{leituras}/{esperado} leituras persistidas"
                    elif not passagem:
                        estado = f"{leituras} leituras persistidas"
                        pendentes.remove(epc)
                    else:
                        parametros_passagem = {**parametros, "inicio": baseline.passagem_id}
                        if programa:
                            linhas = conn.execute(consulta_passagens, parametros_passagem).all()
                            confirmadas = [linha for linha in linhas
                                           if linha.direcao_status == "confirmed"]
                            atual = [linha.direcao for linha in confirmadas]
                            desejada = direcoes[epc]
                            if atual != desejada[:len(atual)]:
                                raise RuntimeError(f"EPC {epc}: passagens {atual}; esperado {desejada}")
                            linha = confirmadas[-1] if len(confirmadas) == len(desejada) else None
                        else:
                            linha = conn.execute(consulta_passagem,
                                                 parametros_passagem).one_or_none()
                        if linha is None:
                            detalhe = (f" {len(confirmadas)}/{len(direcoes[epc])} passagens"
                                       if programa else "")
                            estado = f"{leituras} leituras;{detalhe} passagem pendente"
                        elif linha.direcao_status != "confirmed":
                            estado = (f"passagem {linha.id}: direção "
                                      f"{linha.direcao_status or 'pendente'}")
                        else:
                            movimento = conn.execute(text(
                                "SELECT h.id, h.equipamento_id, e.ultima_zona_id "
                                "FROM historico_movimentacoes h "
                                "JOIN equipamentos e ON e.id = h.equipamento_id "
                                "WHERE h.passagem_id = :id ORDER BY h.id DESC LIMIT 1"
                            ), {"id": linha.id}).one_or_none()
                            if movimento is None:
                                estado = f"passagem {linha.id} confirmada; movimento pendente"
                            elif movimento.ultima_zona_id != linha.zona_destino_id:
                                estado = (f"movimento {movimento.id}; última zona do "
                                          "equipamento ainda não atualizada")
                            else:
                                estado = (f"OK: {leituras} leituras, passagem {linha.id} "
                                          f"{linha.direcao}, movimento {movimento.id}, "
                                          f"equipamento {movimento.equipamento_id} "
                                          f"na zona {movimento.ultima_zona_id}")
                                pendentes.remove(epc)
                    if ultimo_estado.get(epc) != estado:
                        print(f"EPC {epc}: {estado}", flush=True)
                        ultimo_estado[epc] = estado
                if not progresso_atual and any(
                    quantidade < esperados[epc] for epc, quantidade in leituras_vistas.items()
                ):
                    # Uma sessão MQTT durável pode estar esvaziando a fila de
                    # um ensaio anterior antes de chegar às mensagens atuais.
                    ultimo_id = conn.scalar(text(
                        "SELECT COALESCE(MAX(id), 0) FROM leituras_brutas"
                    ))
                    if ultimo_id > ultimo_id_global:
                        ultimo_id_global = ultimo_id
                        fim_sem_progresso = time.monotonic() + timeout
                        print("Ingestor ainda gravando leituras pendentes no banco...",
                              flush=True)
            if pendentes:
                time.sleep(0.5)
        if pendentes:
            detalhes = "; ".join(f"{epc}: {ultimo_estado.get(epc, 'sem dados')}"
                                 for epc in sorted(pendentes))
            motivo = (f"sem progresso por {timeout:g}s" if time.monotonic() < fim_total
                      else f"limite total de {limite_total:g}s atingido")
            raise RuntimeError(f"teste sintético não concluiu ({motivo}): {detalhes}")
        print(f"Teste sintético concluído para {len(epcs)} EPC(s)", flush=True)
    finally:
        engine.dispose()
