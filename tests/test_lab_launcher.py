"""Valida o bootstrap de domínio e a sequência publicada pelo launcher."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from io import StringIO
from types import SimpleNamespace

import psutil
import pytest
from sqlalchemy import func, select

from db.models import (
    Antena,
    AssociacaoTagEquipamento,
    Equipamento,
    Leitor,
    MapeamentoAntenaPortal,
    Portal,
    Tag,
    TipoEquipamento,
    Zona,
)
from rfid_ingestion.config import Settings
from rfid_ingestion.parsing import build_event
from tools.lab_launcher import cli, docker_env, session, synthetic, terminals, watch
from tools.lab_launcher.config import carregar
from tools.lab_launcher.seed import semear, semear_epcs_sinteticos


def test_seed_laboratorio_reexecutavel(db):
    primeiro = semear(db)
    segundo = semear(db)
    assert primeiro["leitor"] == "criado"
    assert segundo["leitor"] == "reutilizado"
    assert db.scalar(select(func.count()).select_from(Leitor)) == 1
    assert db.scalar(select(func.count()).select_from(Zona)) == 2
    assert db.scalar(select(func.count()).select_from(Portal)) == 1
    assert db.scalar(select(func.count()).select_from(Antena)) == 2
    assert db.scalar(select(func.count()).select_from(MapeamentoAntenaPortal)) == 2
    lados = db.scalars(select(MapeamentoAntenaPortal.lado).order_by(MapeamentoAntenaPortal.lado))
    assert list(lados) == ["a", "b"]


def test_epcs_sinteticos_criam_vinculos_reutilizaveis(db):
    semear(db)
    epcs = synthetic.epcs_padrao(2)
    primeiro = semear_epcs_sinteticos(db, epcs)
    segundo = semear_epcs_sinteticos(db, epcs)
    assert all("equipamento criado" in valor for valor in primeiro.values())
    assert all("vínculo existente" in valor for valor in segundo.values())
    assert db.scalar(select(func.count()).select_from(TipoEquipamento)) == 1
    assert db.scalar(select(func.count()).select_from(Equipamento)) == 2
    assert db.scalar(select(func.count()).select_from(Tag)) == 2
    assert db.scalar(select(func.count()).select_from(AssociacaoTagEquipamento)) == 2


def test_publicador_emite_mesmo_epc_em_duas_portas(monkeypatch):
    publicados = []

    class Resultado:
        def wait_for_publish(self, timeout):
            assert timeout == 10

        def is_published(self):
            return True

    class Cliente:
        def connect(self, host, port, keepalive):
            assert (host, port) == ("localhost", 1883)

        def loop_start(self):
            self.on_connect(self, None, None, SimpleNamespace(is_failure=False), None)

        def publish(self, topic, payload, qos):
            publicados.append((topic, json.loads(payload), qos))
            return Resultado()

        def disconnect(self):
            pass

        def loop_stop(self):
            pass

    monkeypatch.setattr(synthetic, "create_client", lambda settings: Cliente())
    monkeypatch.setattr(synthetic.time, "sleep", lambda seconds: None)
    total = synthetic.publicar(
        {"MQTT_HOST": "localhost", "MQTT_PORT": "1883", "MQTT_MODE": "local"},
        "reader-01", epcs=["e2801190a502006016c32f62"], passagem=True, intervalo=0.5,
    )
    assert total == 6
    assert [p[1]["antenna"] for p in publicados] == [1, 1, 1, 2, 2, 2]
    assert all(p[1]["epc"] == "E2801190A502006016C32F62" for p in publicados)
    assert all(p[0] == "easy/dev/hupaa/portal-01/reader-01/readings" for p in publicados)
    assert all(p[2] == 1 for p in publicados)
    assert len({p[1]["timestamp"] for p in publicados}) == 6
    settings = Settings.from_env({"EZ700_TIMESTAMP_FORMAT": "counter"})
    for topic, payload, _ in publicados:
        evento = build_event(topic=topic, qos=1, retain=False,
                             payload=json.dumps(payload).encode(), settings=settings,
                             received_at=datetime.now(timezone.utc))
        assert evento["validation_errors"] == []
        assert evento["canonical_event"]["metadata"]["timestamp_original"] == payload[
            "timestamp"
        ]


def test_epcs_padrao_sao_reutilizaveis_sem_colisao():
    assert synthetic.epcs_padrao(3) == synthetic.epcs_padrao(3)
    assert len(set(synthetic.epcs_padrao(3))) == 3


def test_modo_local_nao_usa_database_url_externa_do_shell(monkeypatch, tmp_path):
    arquivo = tmp_path / ".env.local"
    arquivo.write_text(
        "DATABASE_URL=postgresql+psycopg2://dev:dev@old-host:5432/old\n"
        "POSTGRES_USER=dev\nPOSTGRES_PASSWORD=dev\nPOSTGRES_DB=lab\n"
        "COMPOSE_PROJECT_NAME=rfid-hospital-local\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://user:pass@external/db")
    _, valores = carregar("local", arquivo, False)
    assert valores["DATABASE_URL"].endswith("@localhost:5432/lab")


def test_menu_oferece_os_tres_cenarios_pedidos(monkeypatch):
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    casos = {
        "1": ("local", "synthetic"),
        "2": ("local", "physical"),
        "3": ("managed", "physical"),
        "4": ("managed", "synthetic"),
    }
    for escolha, esperado in casos.items():
        monkeypatch.setattr(cli.typer, "prompt", lambda *args, escolha=escolha, **kwargs: escolha)
        assert cli._cenario(None, None) == esperado


def test_detecta_processo_do_host_na_porta_mqtt(monkeypatch):
    conexoes = [
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=1883), pid=321),
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=9999), pid=654),
    ]
    monkeypatch.setattr(docker_env.psutil, "net_connections", lambda kind: conexoes)
    monkeypatch.setattr(docker_env.psutil, "Process", lambda pid: SimpleNamespace(
        name=lambda: "mosquitto.exe", create_time=lambda: 123.0,
    ))
    bloqueios = docker_env.processos_nas_portas((1883, 5432))
    assert bloqueios == [docker_env.HostBlocker(321, "mosquitto.exe", (1883,), 123.0)]


def test_prepara_porta_encerrando_apenas_bloqueador_confirmado(monkeypatch):
    bloqueio = docker_env.HostBlocker(321, "mosquitto.exe", (1883,), 123.0)
    encontrados = iter(([bloqueio], []))
    encerrados = []
    monkeypatch.setattr(cli, "conflitos", lambda portas, projeto: [])
    monkeypatch.setattr(cli, "portas_do_projeto", lambda portas, projeto: set())
    monkeypatch.setattr(cli, "processos_nas_portas", lambda portas, ignorar=None: next(
        encontrados, []
    ))
    monkeypatch.setattr(cli, "encerrar_processos", lambda itens: encerrados.extend(itens))
    monkeypatch.setattr(cli, "porta_disponivel", lambda endereco, porta: True)
    monkeypatch.setattr(cli.typer, "confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    cli._preparar_portas({1883: "0.0.0.0", 5432: "127.0.0.1"}, "laboratorio", False, True)
    assert encerrados == [bloqueio]


def test_stop_sinaliza_observadores(monkeypatch, tmp_path):
    monkeypatch.setattr(session, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(session, "STATE", tmp_path / "session.json")
    marker = session.iniciar()
    monkeypatch.setenv("LAB_SESSION_MARKER", str(marker))
    assert watch._ativo()
    session.parar()
    assert not watch._ativo()


def test_abre_tres_observadores_em_terminais_separados(monkeypatch, tmp_path):
    chamadas = []
    monkeypatch.setattr(terminals.shutil, "which", lambda nome: nome)
    monkeypatch.setattr(terminals.subprocess, "Popen", lambda args, **kwargs: chamadas.append(
        (args, kwargs)
    ))
    marker = tmp_path / "active"
    terminals.abrir(tmp_path / ".env.local", "local", "ingestor-local", {}, marker)
    assert len(chamadas) == 3
    for (args, kwargs), kind in zip(chamadas, ("mqtt", "logs", "db"), strict=True):
        assert args[1] == "/k"
        assert args[2].endswith("watch_windows.cmd")
        assert kwargs["env"]["LAB_WATCH_KIND"] == kind
        assert kwargs["env"]["LAB_WATCH_PYTHON"] == terminals.sys.executable
        assert kwargs["creationflags"] == terminals.subprocess.CREATE_NEW_CONSOLE
        assert kwargs["env"]["LAB_SESSION_MARKER"] == str(marker)


def test_ubuntu_abre_observadores_com_bash_em_terminais_separados(monkeypatch, tmp_path):
    chamadas = []
    monkeypatch.setattr(terminals, "_sistema", lambda: "posix")
    monkeypatch.setattr(terminals.shutil, "which", lambda nome: (
        "/usr/bin/gnome-terminal" if nome == "gnome-terminal" else None
    ))
    monkeypatch.setattr(terminals.subprocess, "Popen", lambda args, **kwargs: chamadas.append(
        (args, kwargs)
    ))
    terminals.abrir(tmp_path / ".env", "local", "ingestor-local",
                    {"DISPLAY": ":0"}, tmp_path / "active")
    assert len(chamadas) == 3
    for (args, kwargs), kind in zip(chamadas, ("mqtt", "logs", "db"), strict=True):
        assert args[0] == "/usr/bin/gnome-terminal"
        assert args[-3:-1] == ["bash", "-lc"]
        assert f"watch {kind}" in args[-1]
        assert kwargs["cwd"] == terminals.ROOT


def test_ubuntu_sem_interface_grafica_usa_tmux(monkeypatch, tmp_path):
    comandos = []
    monkeypatch.setattr(terminals, "_sistema", lambda: "posix")
    monkeypatch.setattr(terminals, "_TMUX_SESSION", None)
    monkeypatch.setattr(terminals.shutil, "which", lambda nome: (
        "/usr/bin/tmux" if nome == "tmux" else "/usr/bin/gnome-terminal"
    ))
    monkeypatch.setattr(terminals.subprocess, "run", lambda args, **kwargs: (
        comandos.append(args) or SimpleNamespace(returncode=0)
    ))
    terminals.abrir(tmp_path / ".env", "local", "ingestor-local", {}, tmp_path / "active")
    assert [args[1] for args in comandos] == [
        "new-session", "split-window", "split-window", "select-layout"
    ]
    assert terminals._TMUX_SESSION is not None


def test_erro_docker_mostra_causa_sem_expor_credenciais(monkeypatch):
    senha = "senha-do-laboratorio"
    monkeypatch.setattr(docker_env.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=1,
        stderr=f"falha de conexão em postgresql://usuario:{senha}@host/db; PASSWORD={senha}",
        stdout="",
    ))
    with pytest.raises(RuntimeError, match="falha de conexão") as erro:
        docker_env.executar(["docker", "compose", "up"],
                            env={"POSTGRES_PASSWORD": senha})
    assert senha not in str(erro.value)
    assert "[oculto]" in str(erro.value)


def test_build_mostra_progresso_e_preserva_erro_sem_senha(monkeypatch, capsys):
    senha = "senha-da-base"

    class Processo:
        stdout = StringIO(f"#1 carregando Dockerfile\n#2 falha em db://u:{senha}@host/base\n")

        def wait(self):
            return 17

    monkeypatch.setattr(docker_env.subprocess, "Popen", lambda *args, **kwargs: Processo())
    with pytest.raises(RuntimeError, match="código 17") as erro:
        docker_env.executar(["docker", "compose", "up"],
                            env={"POSTGRES_PASSWORD": senha}, mostrar=True)
    saida = capsys.readouterr().out
    assert "carregando Dockerfile" in saida
    assert "falha em" in str(erro.value)
    assert senha not in saida + str(erro.value)


def test_falha_de_migration_inclui_log_do_servico(monkeypatch, tmp_path):
    monkeypatch.setattr(docker_env, "compose", lambda *args, **kwargs: (
        "container-id" if "ps" in args else "alembic: tabela ausente"
    ))
    monkeypatch.setattr(docker_env, "executar", lambda *args, **kwargs: json.dumps(
        {"Status": "exited", "ExitCode": 2}
    ))
    with pytest.raises(RuntimeError, match="alembic: tabela ausente"):
        docker_env.aguardar(tmp_path / ".env", "local", "migrate-local", completo=True)
