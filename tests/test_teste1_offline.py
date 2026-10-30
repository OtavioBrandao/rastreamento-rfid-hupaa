"""Protege o teste 1 contra downloads e configuração externa acidental."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest

from api.simulacao.config import carregar as config_simulador
from scripts import dev
from tools.lab_launcher import cli, docker_env


@pytest.mark.parametrize("offline", [True, False])
def test_compose_offline_proibe_download_e_build(monkeypatch, tmp_path, offline):
    comandos = []
    monkeypatch.setattr(docker_env, "executar", lambda args, **kw: comandos.append(args))
    ambiente = {"RFID_LAB_OFFLINE": "1"} if offline else {}
    docker_env.compose(tmp_path / "perfil", "local", "up", "-d", "migrate-local", env=ambiente)
    comando = comandos[0]
    assert ("--no-build" in comando) == offline
    assert ("never" in comando) == offline
    assert any(arg.endswith("compose.offline.yaml") for arg in comando) == offline


def test_imagem_ausente_interrompe_antes_de_remover_volumes(monkeypatch, tmp_path, capsys):
    comandos = []
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(cli, "carregar", lambda *a: (tmp_path / "perfil", {}))
    monkeypatch.setattr(cli, "compose", lambda *a, **k: comandos.append(a))

    def ausente(*args):
        raise ValueError("teste 1 offline: imagens locais indisponíveis")

    monkeypatch.setattr(cli, "verificar_imagens_locais", ausente)
    with pytest.raises(cli.typer.Exit):
        cli.start(env="local", source="synthetic", fresh=True, no_terminals=True)
    assert not comandos
    assert "imagens locais indisponíveis" in capsys.readouterr().err


def test_launcher_sintetico_local_ativa_offline_em_todas_as_subidas(monkeypatch, tmp_path):
    comandos = []
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(cli, "carregar", lambda *a: (tmp_path / "perfil", {}))
    monkeypatch.setattr(cli, "verificar_imagens_locais", lambda *a: None)
    monkeypatch.setattr(cli, "_preparar_portas", lambda *a: None)
    monkeypatch.setattr(cli, "aguardar", lambda *a, **k: None)
    monkeypatch.setattr(cli, "executar", lambda *a, **k: None)
    monkeypatch.setattr(cli, "compose", lambda *a, **kw: comandos.append((a, kw)))
    cli.start(env="local", source="synthetic", reuse=True, no_terminals=True)
    assert len(comandos) == 3
    assert all(kw["env"]["RFID_LAB_OFFLINE"] == "1" for _, kw in comandos)
    assert all("--build" not in args for args, _ in comandos)


def test_preflight_inspeciona_imagens_sem_pull(monkeypatch, tmp_path):
    comandos = []
    monkeypatch.setattr(docker_env, "compose", lambda *a, **k: "postgres:local\napp:local")

    def executar(args, **kwargs):
        comandos.append(args)
        if args[-1] == "app:local":
            raise RuntimeError("ausente")
        return "[]"

    monkeypatch.setattr(docker_env, "executar", executar)
    with pytest.raises(ValueError, match="app:local"):
        docker_env.verificar_imagens_locais(tmp_path / "perfil", {})
    assert all(args[:3] == ["docker", "image", "inspect"] for args in comandos)
    assert len(comandos) == 2


def test_frontend_ausente_offline_nunca_instala(monkeypatch, tmp_path):
    monkeypatch.setattr(dev, "FRONTEND", tmp_path)
    chamadas = []
    monkeypatch.setattr(dev.subprocess, "run", lambda *a, **k: chamadas.append(a))
    with pytest.raises(SystemExit, match="Nenhum download"):
        dev.preparar_frontend("npm", offline=True)
    assert chamadas == []
    vite = tmp_path / "node_modules" / "vite" / "bin" / "vite.js"
    vite.parent.mkdir(parents=True)
    vite.touch()
    dev.preparar_frontend("npm", offline=True)
    assert chamadas == []


def test_simulador_local_sobrepoe_broker_externo():
    ambiente = {
        "SIMULADOR_MQTT_HOST": "externo.invalid", "SIMULADOR_MQTT_MODE": "cloud",
        "SIMULADOR_MQTT_TOPICO_RELAY": "easy/dev/hupaa/portal/externo/readings",
        "SIMULADOR_MQTT_TOPICO_PERMITIDO": "outro/topico",
    }
    ambiente.update(dev.ambiente_simulador("local", {"MQTT_LOCAL_PORT": "18891"}))
    config = config_simulador(ambiente)
    assert config.habilitado
    assert config.mqtt["MQTT_HOST"] == "127.0.0.1"
    assert config.mqtt["MQTT_PORT"] == "18891"
    assert config.mqtt["MQTT_MODE"] == "local"
    assert not config.topico_relay
    assert not config.topico_permitido


def test_sonda_local_ignora_proxy_externo(monkeypatch):
    class Resposta(BaseHTTPRequestHandler):
        """Servidor HTTP local mínimo para testar a sonda real."""

        def do_GET(self):
            """Responde à sonda de saúde."""
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            """Suprime logs HTTP de teste."""

    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setenv("NO_PROXY", "")
    servidor = HTTPServer(("127.0.0.1", 0), Resposta)
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    try:
        assert dev.aguardar_http(f"http://127.0.0.1:{servidor.server_port}/health",
                                 SimpleNamespace(poll=lambda: None), timeout=2)
    finally:
        servidor.shutdown()
        servidor.server_close()
        thread.join()


@pytest.mark.skipif(not shutil.which("docker"), reason="exige Docker Compose")
def test_override_offline_usa_codigo_atual_e_preserva_volume_de_dados():
    resultado = subprocess.run(
        ["docker", "compose", "-f", "deploy/compose.yaml", "-f", "deploy/compose.offline.yaml",
         "--env-file", "config/environments/.env.local.example", "--profile", "local",
         "config", "--format", "json"],
        cwd=dev.ROOT, env=dict(os.environ, COMPOSE_PROJECT_NAME="rfid-check-offline"),
        check=True, capture_output=True, text=True,
    )
    config = json.loads(resultado.stdout)
    for servico in ("migrate-local", "ingestor-local"):
        volumes = {v["target"]: v for v in config["services"][servico]["volumes"]}
        assert volumes["/app/rfid_ingestion"]["source"] == str(dev.ROOT / "rfid_ingestion")
        assert volumes["/app/alembic"]["read_only"]
    dados = next(v for v in config["services"]["ingestor-local"]["volumes"]
                 if v["target"] == "/app/data")
    assert dados["source"] == str(dev.ROOT / "data")
    assert not dados.get("read_only", False)
