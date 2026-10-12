"""Observadores de MQTT e leituras persistidas para os terminais do laboratório."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from threading import Event
from uuid import uuid4

from sqlalchemy import create_engine, text

from rfid_ingestion.config import Settings
from rfid_ingestion.connection import create_client

from .config import ROOT
from .docker_env import _limpar_saida


def _ativo() -> bool:
    marker = os.environ.get("LAB_SESSION_MARKER")
    return marker is None or Path(marker).exists()


def _pronto(kind: str) -> None:
    marker = os.environ.get("LAB_SESSION_MARKER")
    if marker:
        path = Path(marker)
        path.with_name(f"{path.stem}.{kind}.ready").touch()


def mqtt_watch() -> None:
    source = dict(os.environ, MQTT_CLIENT_ID=f"lab-watch-{uuid4().hex[:12]}")
    settings = Settings.from_env(source)
    client = create_client(settings)
    falha = Event()

    def on_connect(c, _userdata, _flags, reason_code, _properties):
        if reason_code.is_failure:
            falha.set()
            return
        c.subscribe(settings.mqtt_topic, qos=1)
        print(f"Inscrito em {settings.mqtt_topic}", flush=True)
        _pronto("mqtt")

    def on_message(_client, _userdata, msg):
        print(f"{msg.topic} {msg.payload.decode('utf-8', errors='replace')}", flush=True)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(settings.mqtt_host, settings.mqtt_port, settings.mqtt_keepalive)
    try:
        client.loop_start()
        while _ativo():
            if falha.is_set():
                raise RuntimeError("conexão MQTT do observador recusada")
            time.sleep(0.5)
    finally:
        client.disconnect()
        client.loop_stop()


def db_watch() -> None:
    url = os.environ.get("APP_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("APP_DATABASE_URL ou DATABASE_URL ausente")
    engine = create_engine(url, pool_pre_ping=True)
    # Começa do fim: com o histórico grande, partir do id 0 reexibia leituras de dias
    # anteriores por dezenas de minutos, como se estivessem chegando agora.
    with engine.connect() as conn:
        ultimo = conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM leituras_brutas")).scalar_one()
        ultimo_movimento = conn.execute(text(
            "SELECT COALESCE(MAX(id), 0) FROM historico_movimentacoes")).scalar_one()
        # Passagens já existentes só voltam a aparecer se mudarem de estado.
        passagens_vistas: dict[int, tuple] = {
            linha.id: (linha.direcao_status, linha.direcao, linha.zona_origem_id,
                       linha.zona_destino_id)
            for linha in conn.execute(text(
                "SELECT id, direcao_status, direcao, zona_origem_id, zona_destino_id "
                "FROM passagens ORDER BY id DESC LIMIT 100")).all()
        }
    ultimo_status = 0.0
    print("Acompanhando leituras, passagens, movimentos e última zona...", flush=True)
    try:
        while _ativo():
            with engine.connect() as conn:
                linhas = conn.execute(text(
                    "SELECT id, epc, antena_id, lido_em FROM leituras_brutas "
                    "WHERE id > :ultimo ORDER BY id LIMIT 100"
                ), {"ultimo": ultimo}).all()
            for linha in linhas:
                print(f"id={linha.id} epc={linha.epc} antena={linha.antena_id} "
                      f"lido_em={linha.lido_em}", flush=True)
                ultimo = linha.id
            with engine.connect() as conn:
                passagens = conn.execute(text(
                    "SELECT p.id, p.epc, p.direcao_status, p.direcao, "
                    "p.zona_origem_id, p.zona_destino_id "
                    "FROM passagens p ORDER BY p.id DESC LIMIT 100"
                )).all()
                movimentos = conn.execute(text(
                    "SELECT h.id, h.epc, h.equipamento_id, h.zona_destino_id, "
                    "e.ultima_zona_id FROM historico_movimentacoes h "
                    "JOIN equipamentos e ON e.id = h.equipamento_id "
                    "WHERE h.id > :ultimo ORDER BY h.id LIMIT 100"
                ), {"ultimo": ultimo_movimento}).all()
            _pronto("db")
            agora = time.monotonic()
            if agora - ultimo_status >= 15:
                print("Banco conectado; monitorando leituras e movimentações...", flush=True)
                ultimo_status = agora
            for linha in reversed(passagens):
                estado = (linha.direcao_status, linha.direcao,
                          linha.zona_origem_id, linha.zona_destino_id)
                if passagens_vistas.get(linha.id) != estado:
                    print(f"passagem={linha.id} epc={linha.epc} "
                          f"status={linha.direcao_status or 'pendente'} "
                          f"direção={linha.direcao or '-'} "
                          f"zonas={linha.zona_origem_id}->{linha.zona_destino_id}",
                          flush=True)
                    passagens_vistas[linha.id] = estado
            recentes = {linha.id for linha in passagens}
            passagens_vistas = {chave: valor for chave, valor in passagens_vistas.items()
                               if chave in recentes}
            for linha in movimentos:
                print(f"movimento={linha.id} epc={linha.epc} "
                      f"equipamento={linha.equipamento_id} "
                      f"destino={linha.zona_destino_id} "
                      f"última_zona={linha.ultima_zona_id}", flush=True)
                ultimo_movimento = linha.id
            time.sleep(2)
    finally:
        engine.dispose()


def logs_watch() -> None:
    arquivo = os.environ["LAB_COMPOSE_ENV_FILE"]
    perfil = os.environ["LAB_COMPOSE_PROFILE"]
    servico = os.environ["LAB_INGESTOR_SERVICE"]
    processo = subprocess.Popen(
        ["docker", "compose", "--env-file", arquivo, "--profile", perfil,
         "logs", "-f", servico], cwd=ROOT, env=os.environ.copy()
    )
    try:
        while _ativo() and processo.poll() is None:
            _pronto("logs")
            time.sleep(0.5)
    finally:
        if processo.poll() is None:
            processo.terminate()
            try:
                processo.wait(timeout=3)
            except subprocess.TimeoutExpired:
                processo.kill()
                processo.wait()
    if processo.returncode not in (None, 0) and _ativo():
        raise RuntimeError(f"docker compose logs terminou com código {processo.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("mqtt", "db", "logs"))
    parser.add_argument("--session-file", type=Path)
    args = parser.parse_args()
    if args.session_file is not None:
        valores = json.loads(args.session_file.read_text(encoding="utf-8"))
        if not isinstance(valores, dict) or any(
            not isinstance(chave, str) or not isinstance(valor, str)
            for chave, valor in valores.items()
        ):
            raise ValueError("configuração local dos observadores inválida")
        os.environ.update(valores)
    kind = args.kind
    if kind == "mqtt":
        mqtt_watch()
    elif kind == "db":
        db_watch()
    else:
        logs_watch()


if __name__ == "__main__":
    try:
        main()
    except Exception as erro:
        print("Falha no observador: " + _limpar_saida(str(erro), dict(os.environ)),
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
