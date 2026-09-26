"""Confere o percurso sintético até passagem, movimento e última zona."""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import create_engine, text


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
             passagem: bool, mensagens: int, timeout: float = 30) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    pendentes = set(epc.upper() for epc in epcs)
    ultimo_estado: dict[str, str] = {}
    fim = time.monotonic() + timeout
    try:
        while pendentes and time.monotonic() < fim:
            with engine.connect() as conn:
                for epc in tuple(pendentes):
                    leituras = conn.scalar(text(
                        "SELECT COUNT(*) FROM leituras_brutas "
                        "WHERE id > :inicio AND epc = :epc"
                    ), {"inicio": baseline.leitura_id, "epc": epc})
                    esperado = mensagens
                    if leituras < esperado:
                        estado = f"{leituras}/{esperado} leituras persistidas"
                    elif not passagem:
                        estado = f"{leituras} leituras persistidas"
                        pendentes.remove(epc)
                    else:
                        linha = conn.execute(text(
                            "SELECT id, direcao_status, direcao, zona_destino_id "
                            "FROM passagens WHERE id > :inicio AND epc = :epc "
                            "ORDER BY id DESC LIMIT 1"
                        ), {"inicio": baseline.passagem_id, "epc": epc}).one_or_none()
                        if linha is None:
                            estado = f"{leituras} leituras; passagem pendente"
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
            if pendentes:
                time.sleep(0.5)
        if pendentes:
            detalhes = "; ".join(f"{epc}: {ultimo_estado.get(epc, 'sem dados')}"
                                 for epc in sorted(pendentes))
            raise RuntimeError(f"teste sintético não concluiu em {timeout:g}s: {detalhes}")
        print(f"Teste sintético concluído para {len(epcs)} EPC(s)", flush=True)
    finally:
        engine.dispose()
