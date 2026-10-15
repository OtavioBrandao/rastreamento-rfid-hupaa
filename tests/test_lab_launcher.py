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
    Zona,
)
from rfid_ingestion.config import Settings
from tools.lab_launcher import cli, docker_env, session, tags, terminals, watch
from tools.lab_launcher.config import carregar
from tools.lab_launcher.seed import TIPO_SINTETICO, epcs_por_nome, semear, semear_equipamentos


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
    assert {zona.nome: zona.referencia_planta for zona in db.scalars(select(Zona))} == {
        "Zona A": "sala-a", "Zona B": "sala-b"}


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


def test_menu_limpa_tela_e_oferece_os_cenarios(monkeypatch):
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    limpezas = []
    monkeypatch.setattr(cli.click, "clear", lambda: limpezas.append(True))
    casos = {
        "1": ("local", "synthetic"),
        "2": ("local", "physical"),
        "3": ("managed", "physical"),
        "4": ("managed", "synthetic"),
    }
    for escolha, esperado in casos.items():
        monkeypatch.setattr(cli.typer, "prompt", lambda *args, escolha=escolha, **kwargs: escolha)
        assert cli._cenario(None, None) == esperado
    assert len(limpezas) == 4


def test_modo_externo_sintetico_exige_perfil_de_publicacao(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    valores = {"MQTT_USERNAME": "ingestor", "MQTT_PASSWORD": "segredo-ingestor"}
    with pytest.raises(ValueError, match="--publisher-env-file"):
        cli._perfil_publicador("managed", valores, None, False)

    perfil = tmp_path / "config" / "environments" / ".env.cloud.reader-01"
    perfil.parent.mkdir(parents=True)
    perfil.write_text(
        "MQTT_USERNAME=leitor\nMQTT_PASSWORD=segredo-leitor\n"
        "MQTT_TOPIC=easy/dev/hupaa/portal-01/reader-01/readings\n",
        encoding="utf-8",
    )
    publicado = cli._perfil_publicador("managed", valores, None, False)
    assert publicado["MQTT_USERNAME"] == "leitor"
    assert publicado["MQTT_TOPIC"] == "easy/dev/hupaa/portal-01/reader-01/readings"
    assert valores["MQTT_USERNAME"] == "ingestor"

    perfil.write_text(
        "MQTT_USERNAME=ingestor\nMQTT_PASSWORD=segredo-ingestor\n"
        "MQTT_TOPIC=easy/dev/hupaa/portal-01/reader-01/readings\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="separada do ingestor"):
        cli._perfil_publicador("managed", valores, perfil, False)


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
    watch._pronto("db")
    assert (tmp_path / f"{marker.stem}.db.ready").exists()
    config = tmp_path / f"{marker.stem}.watch.json"
    config.write_text("{}", encoding="utf-8")
    session.parar()
    assert not watch._ativo()
    assert not (tmp_path / f"{marker.stem}.db.ready").exists()
    assert not config.exists()


def test_stop_remove_configuracao_orfa_mesmo_sem_estado(monkeypatch, tmp_path):
    monkeypatch.setattr(session, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(session, "STATE", tmp_path / "session.json")
    config = tmp_path / ("a" * 32 + ".watch.json")
    config.write_text("{}", encoding="utf-8")
    session.parar()
    assert not config.exists()


def test_windows_terminal_abre_tres_abas_nomeadas(monkeypatch, tmp_path):
    chamadas = []
    monkeypatch.setattr(terminals, "_sistema", lambda: "nt")
    monkeypatch.setattr(terminals.shutil, "which", lambda nome: nome)
    monkeypatch.setattr(terminals, "_aguardar_prontos", lambda *args, **kwargs: ())
    monkeypatch.setattr(terminals.subprocess, "Popen", lambda args, **kwargs: chamadas.append(
        (args, kwargs)
    ))
    marker = tmp_path / "active"
    env = {"APP_DATABASE_URL": "postgresql://u:senha@localhost/db",
           "MQTT_PASSWORD": "segredo", "UNRELATED_SECRET": "nao-gravar"}
    terminals.abrir(tmp_path / ".env.local", "local", "ingestor-local", env, marker)
    assert len(chamadas) == 1
    args, _ = chamadas[0]
    assert args[:4] == ["wt.exe", "-w", "0", "new-tab"]
    assert args.count("new-tab") == 3
    assert args.count(";") == 2
    assert [args[i + 1] for i, item in enumerate(args) if item == "--title"] == [
        "MQTT", "Ingestor", "Banco"
    ]
    for kind, titulo in (("mqtt", "MQTT"), ("logs", "Ingestor"), ("db", "Banco")):
        assert [terminals.sys.executable, kind, titulo] in [
            args[i:i + 3] for i in range(len(args) - 2)
        ]
    config = tmp_path / "active.watch.json"
    valores = json.loads(config.read_text(encoding="utf-8"))
    assert valores["APP_DATABASE_URL"] == env["APP_DATABASE_URL"]
    assert valores["MQTT_PASSWORD"] == "segredo"
    assert valores["LAB_SESSION_MARKER"] == str(marker)
    assert "UNRELATED_SECRET" not in valores
    assert "segredo" not in " ".join(args)


def test_windows_sem_wt_abre_janelas_com_titulo(monkeypatch, tmp_path):
    chamadas = []
    monkeypatch.setattr(terminals, "_sistema", lambda: "nt")
    monkeypatch.setattr(terminals.subprocess, "CREATE_NEW_CONSOLE", 16, raising=False)
    monkeypatch.setattr(terminals.shutil, "which", lambda nome: (
        "cmd.exe" if nome == "cmd.exe" else None
    ))
    monkeypatch.setattr(terminals, "_aguardar_prontos", lambda *args, **kwargs: ())
    monkeypatch.setattr(terminals.subprocess, "Popen", lambda args, **kwargs: chamadas.append(
        (args, kwargs)
    ))
    terminals.abrir(tmp_path / ".env.local", "local", "ingestor-local", {},
                    tmp_path / "active")
    assert len(chamadas) == 3
    assert [args[-3] for args, _ in chamadas] == ["mqtt", "logs", "db"]
    assert [args[-2] for args, _ in chamadas] == ["MQTT", "Ingestor", "Banco"]
    assert all(kwargs["creationflags"] == 16 for _, kwargs in chamadas)


def test_windows_recupera_observador_que_nao_iniciou_na_aba(monkeypatch, tmp_path):
    chamadas = []
    respostas = iter([("db",), ()])
    monkeypatch.setattr(terminals, "_sistema", lambda: "nt")
    monkeypatch.setattr(terminals.shutil, "which", lambda nome: nome)
    monkeypatch.setattr(terminals, "_aguardar_prontos", lambda *args, **kwargs: next(
        respostas
    ))
    monkeypatch.setattr(terminals.subprocess, "CREATE_NEW_CONSOLE", 16, raising=False)
    monkeypatch.setattr(terminals.subprocess, "Popen", lambda args, **kwargs: chamadas.append(
        (args, kwargs)
    ))
    terminals.abrir(tmp_path / ".env.local", "local", "ingestor-local", {},
                    tmp_path / "active")
    assert len(chamadas) == 2
    assert chamadas[-1][0][0] == "cmd.exe"
    assert chamadas[-1][0][-3] == "db"


def test_observador_carrega_configuracao_local_sem_depender_do_ambiente_do_wt(
    monkeypatch, tmp_path
):
    config = tmp_path / "watch.json"
    config.write_text(json.dumps({"APP_DATABASE_URL": "postgresql://local"}),
                      encoding="utf-8")
    monkeypatch.setenv("APP_DATABASE_URL", "valor-antigo")
    monkeypatch.setattr(watch.sys, "argv", ["watch", "db", "--session-file", str(config)])
    visto = []
    monkeypatch.setattr(watch, "db_watch", lambda: visto.append(
        watch.os.environ["APP_DATABASE_URL"]
    ))
    watch.main()
    assert visto == ["postgresql://local"]


def test_observador_ausente_mostra_nome_do_erro(monkeypatch, tmp_path):
    monkeypatch.setattr(terminals, "_aguardar_prontos", lambda *args, **kwargs: ("db",))
    with pytest.raises(RuntimeError, match="observadores não iniciaram: db"):
        terminals._exigir_prontos(tmp_path / "active")


def test_ubuntu_abre_observadores_com_bash_em_terminais_separados(monkeypatch, tmp_path):
    chamadas = []
    monkeypatch.setattr(terminals, "_sistema", lambda: "posix")
    monkeypatch.setattr(terminals, "_aguardar_prontos", lambda *args, **kwargs: ())
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
    monkeypatch.setattr(terminals, "_aguardar_prontos", lambda *args, **kwargs: ())
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


def test_tags_fisicas_cadastram_equipamentos_com_nome(db):
    semear(db)
    epc_a, epc_b = "3034000000000C40000000E8", "3034000000000C400000012F"
    primeiro = semear_equipamentos(db, [(epc_a.lower(), "Bomba de infusão 01"),
                                        (epc_b, "Monitor multiparâmetro")])
    assert all("equipamento criado" in valor for valor in primeiro.values())
    nomes = set(db.scalars(select(Equipamento.nome)))
    assert nomes == {"Bomba de infusão 01", "Monitor multiparâmetro"}

    segundo = semear_equipamentos(db, [(epc_a, "Bomba de infusão 02")])
    assert "renomeado" in segundo[epc_a]
    assert db.scalar(select(func.count()).select_from(Equipamento)) == 2
    assert db.scalar(select(func.count()).select_from(AssociacaoTagEquipamento)) == 2
    assert "Bomba de infusão 02" in set(db.scalars(select(Equipamento.nome)))


def test_simulador_reaproveita_equipamento_pelo_nome(db):
    from api.service_equipamento import inativar

    semear(db)
    epc = "E2804C41AAAAAAAAAAAAAAAA"
    semear_equipamentos(db, [(epc, "Bomba X")], TIPO_SINTETICO)

    # Nome repetido devolve a tag existente; nome novo fica de fora (ganha EPC sorteado).
    assert epcs_por_nome(db, ["Bomba X ", "Monitor novo"], TIPO_SINTETICO) == {"Bomba X": epc}
    semear_equipamentos(db, [(epc, "Bomba X")], TIPO_SINTETICO)
    assert db.scalar(select(func.count()).select_from(Equipamento)
                     .where(Equipamento.nome == "Bomba X")) == 1

    equipamento = db.scalar(select(Equipamento).where(Equipamento.nome == "Bomba X"))
    inativar(db, equipamento.id)
    assert epcs_por_nome(db, ["bomba x"], TIPO_SINTETICO) == {"bomba x": epc}
    db.refresh(equipamento)
    assert equipamento.status == "ativo"


def test_tag_fisica_nao_renomeia_equipamento_cadastrado_fora_do_laboratorio(db):
    from api.service_associacao import associar
    from api.service_equipamento import criar as criar_equipamento
    from api.service_tipos_equipamento import criar as criar_tipo

    tipo = criar_tipo(db, "Ventilador")
    real = criar_equipamento(db, "Ventilador UTI 3", tipo.id, "PAT-123")
    associar(db, real.id, "E28011B000000C40000000E4")
    resumo = semear_equipamentos(db, [("E28011B000000C40000000E4", "Outro nome")])
    assert "renomeado" not in resumo["E28011B000000C40000000E4"]
    db.refresh(real)
    assert real.nome == "Ventilador UTI 3"


def test_tags_fisicas_por_flag_e_por_pergunta(monkeypatch):
    assert cli._tags_fisicas(["3034000000000c40000000e8=Bomba 01"], "", False) == [
        ("3034000000000C40000000E8", "Bomba 01")]
    with pytest.raises(ValueError, match="EPC=Nome"):
        cli._tags_fisicas(["3034000000000C40000000E8"], "", False)
    assert cli._tags_fisicas(None, "", False) == []

    recentes = [tags.EpcObservado("3034000000000C40000000E8", 10,
                                  datetime(2026, 10, 5, tzinfo=timezone.utc), None)]
    respostas = iter(["1", "Bomba 01", "ZZ", "E28011B000000C4000000132", "Monitor", ""])
    monkeypatch.setattr(tags.typer, "prompt", lambda *args, **kwargs: next(respostas))
    assert tags.perguntar_tags(recentes) == [
        ("3034000000000C40000000E8", "Bomba 01"),
        ("E28011B000000C4000000132", "Monitor"),
    ]


def test_transporte_plain_usa_broker_sem_tls_e_mantem_banco_externo(monkeypatch, tmp_path):
    for chave in ("MQTT_HOST", "MQTT_USERNAME", "MQTT_PASSWORD", "MQTT_PLAIN_HOST"):
        monkeypatch.delenv(chave, raising=False)
    arquivo = tmp_path / ".env.cloud"
    arquivo.write_text(
        "MQTT_HOST=cluster.s1.eu.hivemq.cloud\nMQTT_USERNAME=ingestor\n"
        "MQTT_PASSWORD=segredo\nMQTT_CLIENT_ID=easy-cloud-ingestor\n"
        "MQTT_PLAIN_HOST=broker.hivemq.com\n"
        "DATABASE_URL=postgresql+psycopg2://u:p@db.neon.tech/x\n"
        "APP_DATABASE_URL=postgresql+psycopg2://u:p@db-pool.neon.tech/x\n",
        encoding="utf-8",
    )
    _, valores = carregar("managed", arquivo, False, "plain")
    assert valores["MQTT_HOST"] == "broker.hivemq.com"
    assert valores["MQTT_PORT"] == "1883"
    assert (valores["MQTT_TLS_ENABLED"], valores["MQTT_INSECURE_LAB"]) == ("false", "true")
    assert valores["MQTT_USERNAME"] == ""
    assert valores["APP_DATABASE_URL"].endswith("db-pool.neon.tech/x")
    settings = Settings.from_env(valores)
    assert not settings.mqtt_tls_enabled and settings.mqtt_port == 1883

    _, tls = carregar("managed", arquivo, False)
    assert (tls["MQTT_HOST"], tls["MQTT_TLS_ENABLED"]) == ("cluster.s1.eu.hivemq.cloud", "true")
    with pytest.raises(ValueError, match="somente TLS"):
        cli._avisar_transporte_plain(dict(valores, MQTT_HOST="c.s1.eu.hivemq.cloud"), False)


def test_transporte_e_tags_respeitam_o_modo(monkeypatch):
    assert cli._transporte_escolhido(None, "local", True) == "tls"
    with pytest.raises(ValueError, match="broker externo"):
        cli._transporte_escolhido("plain", "local", False)
    monkeypatch.setattr(cli.typer, "prompt", lambda *args, **kwargs: "2")
    assert cli._transporte_escolhido(None, "managed", True) == "plain"
    assert cli._transporte_escolhido(None, "managed", False) == "tls"


def test_simulador_sem_flet_falha_antes_de_subir_servicos(monkeypatch, capsys):
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda nome: None)
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(cli, "compose", lambda *a, **k: pytest.fail("não deve subir serviços"))
    with pytest.raises(cli.typer.Exit):
        cli.start(env="local", source="synthetic", no_terminals=True)
    assert "requirements/lab.txt" in capsys.readouterr().err


def test_simulador_nao_aceita_tags_do_leitor_fisico(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(cli.typer.Exit):
        cli.start(env="local", source="synthetic", no_terminals=True,
                  tag=["E2801190A502006016C32F62=Bomba"])
    assert "definidos na janela" in capsys.readouterr().err


def test_opcao_sintetica_abre_simulador_com_publicador_e_banco(monkeypatch, tmp_path):
    valores = {"MQTT_HOST": "broker", "MQTT_PORT": "8883", "MQTT_USERNAME": "ingestor",
               "MQTT_PASSWORD": "segredo", "DATABASE_URL": "postgresql://seed",
               "APP_DATABASE_URL": "postgresql://app"}
    arquivo = tmp_path / ".env.cloud"
    abertos = []

    class Processo:
        def __init__(self, comando, cwd, env):
            abertos.append((comando, env))

        def poll(self):
            return 0

        def wait(self):
            return 0

    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    # O simulador roda em processo separado (Popen simulado); o CI não instala o Flet.
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda nome: object())
    monkeypatch.setattr(cli, "carregar", lambda *a, **k: (arquivo, dict(valores)))
    monkeypatch.setattr(cli, "_perfil_publicador", lambda modo, v, *a: dict(
        v, MQTT_USERNAME="leitor", MQTT_PASSWORD="segredo-leitor",
        MQTT_TOPIC="easy/dev/hupaa/portal-01/reader-01/readings"))
    monkeypatch.setattr(cli, "compose", lambda *a, **k: None)
    monkeypatch.setattr(cli, "aguardar", lambda *a, **k: None)
    monkeypatch.setattr(cli, "executar", lambda *a, **k: None)
    monkeypatch.setattr(cli.subprocess, "Popen", Processo)

    cli.start(env="managed", source="synthetic", no_terminals=True)

    comando, env = abertos[0]
    assert comando[1:] == ["-m", "tools.lab_simulator", "--reader-id", "reader-01",
                           "--portal-id", "portal-01"]
    assert env["MQTT_USERNAME"] == "leitor"
    assert env["MQTT_TOPIC"] == "easy/dev/hupaa/portal-01/reader-01/readings"
    assert env["DATABASE_URL"] == "postgresql://seed"


@pytest.mark.parametrize("host, erro", [
    ("c.s1.eu.hivemq.cloud:8883", "sem esquema nem porta"),
    ("mqtt://broker.hivemq.com", "sem esquema nem porta"),
    ("c.s1.eu.hivemq.cloud", "só aceita TLS"),
])
def test_transporte_plain_recusa_host_invalido(monkeypatch, tmp_path, host, erro):
    for chave in ("MQTT_HOST", "MQTT_USERNAME", "MQTT_PASSWORD", "MQTT_PLAIN_HOST"):
        monkeypatch.delenv(chave, raising=False)
    arquivo = tmp_path / ".env.cloud"
    arquivo.write_text(
        f"MQTT_PLAIN_HOST='{host}'\nMQTT_CLIENT_ID=ingestor\n"
        "DATABASE_URL=postgresql://u:p@db/x\nAPP_DATABASE_URL=postgresql://u:p@db/x\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match=erro):
        carregar("managed", arquivo, False, "plain")
