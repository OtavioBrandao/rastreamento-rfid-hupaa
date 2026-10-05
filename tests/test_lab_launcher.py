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
from tools.lab_launcher import cli, docker_env, session, synthetic, tags, terminals, verify, watch
from tools.lab_launcher.config import carregar
from tools.lab_launcher.seed import semear, semear_epcs_sinteticos, semear_equipamentos


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


@pytest.mark.parametrize("cenario,esperado", [
    (2, [("02", "a_para_b"), ("02", "b_para_a"), ("03", "a_para_b"),
         ("02", "a_para_b"), ("03", "b_para_a")]),
    (3, [("02", "a_para_b"), ("03", "a_para_b"), ("03", "b_para_a"),
         ("03", "a_para_b"), ("03", "b_para_a")]),
])
def test_roteiros_multitag_intercalam_leituras_e_direcoes(cenario, esperado):
    epcs = synthetic.epcs_padrao(3)[1:]
    plano = synthetic.programa_multitag(cenario, epcs, 10, 0.5)
    assert len(plano) == 50
    assert all(leitura.porta in (1, 2) for leitura in plano)
    assert sum(leitura.pausa_antes >= 3.5 for leitura in plano) == (2 if cenario == 2 else 3)
    trajetos = {}
    for leitura in plano:
        sufixo = leitura.epc[-2:]
        portas = trajetos.setdefault(sufixo, [])
        if not portas or portas[-1] != leitura.porta:
            portas.append(leitura.porta)
    direcoes = sorted((epc, "a_para_b" if a == 1 else "b_para_a")
                      for epc, portas in trajetos.items()
                      for a, b in zip(portas, portas[1:]))
    assert direcoes == sorted(esperado)
    if cenario == 2:
        assert [leitura.epc for leitura in plano[10:14]] == [epcs[0], epcs[1]] * 2
    else:
        assert trajetos["02"] == [1, 2]


def test_publicador_multitag_preserva_payload_e_contador(monkeypatch):
    enviados = []

    class Ack:
        rc = synthetic.mqtt.MQTT_ERR_SUCCESS

        def wait_for_publish(self, timeout):
            assert timeout == 10

        def is_published(self):
            return True

    class Client:
        def connect(self, *_args):
            pass

        def loop_start(self):
            self.on_connect(self, None, None, SimpleNamespace(is_failure=False), None)

        def publish(self, _topic, payload, qos):
            assert qos == 1
            enviados.append(json.loads(payload))
            return Ack()

        def disconnect(self):
            pass

        def loop_stop(self):
            pass

    monkeypatch.setattr(synthetic, "create_client", lambda *_args: Client())
    monkeypatch.setattr(synthetic.time, "sleep", lambda *_args: None)
    epcs = synthetic.epcs_padrao(3)[1:]
    total = synthetic.publicar(
        {"MQTT_HOST": "localhost", "MQTT_PORT": "1883", "MQTT_MODE": "local"},
        "reader-01", epcs=epcs, passagem=True, intervalo=0.5, mensagens=10,
        contador_inicial=1_234_567, cenario=2)
    assert total == 50
    assert all(list(payload) == ["epc", "rssi", "antenna", "timestamp"] for payload in enviados)
    assert [payload["timestamp"] for payload in enviados] == [str(1_234_567 + i) for i in range(50)]
    assert {payload["epc"] for payload in enviados} == set(epcs)


def test_verificador_multitag_confere_direcoes_e_zona_final(monkeypatch):
    epcs = synthetic.epcs_padrao(3)[1:]
    programa = synthetic.programa_multitag(2, epcs, 10, 0.5)

    class Resultado:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

        def one_or_none(self):
            return self.rows[0] if self.rows else None

    class Conexao:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def scalar(self, _query, params):
            return 30 if params["epc"] == epcs[0] else 20

        def execute(self, query, params):
            if "FROM passagens p" in str(query):
                direcoes = (["a_para_b", "b_para_a", "a_para_b"]
                            if params["epc"] == epcs[0] else ["a_para_b", "b_para_a"])
                return Resultado([SimpleNamespace(id=i + 1, direcao_status="confirmed",
                                                  direcao=direcao,
                                                  zona_destino_id=2 if direcao == "a_para_b" else 1)
                                  for i, direcao in enumerate(direcoes)])
            return Resultado([SimpleNamespace(id=10, equipamento_id=20,
                                              ultima_zona_id=2 if params["id"] == 3 else 1)])

    class Engine:
        def connect(self):
            return Conexao()

        def dispose(self):
            pass

    monkeypatch.setattr(verify, "create_engine", lambda *_args, **_kwargs: Engine())
    verify.conferir("db-local-de-teste", verify.Baseline(0, 0), epcs,
                    passagem=True, mensagens=10, contador_inicial=1_234_567,
                    programa=programa)


def test_menu_roteiros_disponivel_em_todos_os_modos(monkeypatch):
    monkeypatch.setattr(cli.typer, "prompt", lambda *args, **kwargs: "2")
    assert cli._roteiro_escolhido(None, True) == 2
    assert cli._roteiro_escolhido(None, False) == 1
    with pytest.raises(ValueError, match="roteiro de 1 a 3"):
        cli._roteiro_escolhido(4, False)


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
    publicados_raw = []
    pausas = []

    class Resultado:
        rc = synthetic.mqtt.MQTT_ERR_SUCCESS

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
            publicados_raw.append(payload)
            publicados.append((topic, json.loads(payload), qos))
            return Resultado()

        def disconnect(self):
            pass

        def loop_stop(self):
            pass

    monkeypatch.setattr(synthetic, "create_client", lambda settings: Cliente())
    monkeypatch.setattr(synthetic.time, "sleep", lambda seconds: pausas.append(seconds))
    total = synthetic.publicar(
        {"MQTT_HOST": "localhost", "MQTT_PORT": "1883", "MQTT_MODE": "local"},
        "reader-01", epcs=["e2801190a502006016c32f62"], passagem=True, intervalo=0.5,
    )
    assert total == 100
    assert [p[1]["antenna"] for p in publicados] == [1] * 70 + [2] * 30
    assert pausas.count(0.15) == 44
    assert pausas.count(0.5) == 1
    assert all(p[1]["epc"] == "E2801190A502006016C32F62" for p in publicados)
    assert all(p[0] == "easy/dev/hupaa/portal-01/reader-01/readings" for p in publicados)
    assert all(p[2] == 1 for p in publicados)
    assert len({p[1]["timestamp"] for p in publicados}) == 100
    assert all(list(p[1]) == ["epc", "rssi", "antenna", "timestamp"] for p in publicados)
    assert all(raw.startswith('{"epc":"') and ',"rssi":' in raw
               and ',"antenna":' in raw and ',"timestamp":"' in raw
               and " " not in raw for raw in publicados_raw)
    assert all(isinstance(p[1]["timestamp"], str)
               and len(p[1]["timestamp"]) == 7 for p in publicados)
    assert all(-6700 <= p[1]["rssi"] <= -5700 for p in publicados)
    settings = Settings.from_env({"EZ700_TIMESTAMP_FORMAT": "counter"})
    for topic, payload, _ in publicados:
        evento = build_event(topic=topic, qos=1, retain=False,
                             payload=json.dumps(payload).encode(), settings=settings,
                             received_at=datetime.now(timezone.utc))
        assert evento["validation_errors"] == []
        assert evento["canonical_event"]["metadata"]["timestamp_original"] == payload[
            "timestamp"
        ]
        assert evento["canonical_event"]["metadata"]["timestamp_format"] == "received_at_utc"


def test_publicador_indica_falta_de_puback_apos_desconexao(monkeypatch):
    class Resultado:
        rc = synthetic.mqtt.MQTT_ERR_SUCCESS

        def wait_for_publish(self, timeout):
            assert timeout == 10

        def is_published(self):
            return False

    class Cliente:
        def connect(self, *_args):
            pass

        def loop_start(self):
            self.on_connect(self, None, None, SimpleNamespace(is_failure=False), None)

        def publish(self, *_args, **_kwargs):
            self.on_disconnect(self, None, None, None, None)
            return Resultado()

        def disconnect(self):
            pass

        def loop_stop(self):
            pass

    monkeypatch.setattr(synthetic, "create_client", lambda settings: Cliente())
    with pytest.raises(RuntimeError, match="credencial do publicador tem permissão Publish"):
        synthetic.publicar({"MQTT_HOST": "localhost", "MQTT_MODE": "local"},
                           "reader-01", epcs=synthetic.epcs_padrao(1),
                           passagem=True, intervalo=0.5)


def test_epcs_padrao_sao_reutilizaveis_sem_colisao():
    assert synthetic.epcs_padrao(3) == synthetic.epcs_padrao(3)
    assert len(set(synthetic.epcs_padrao(3))) == 3


def test_roteiro_de_100_mensagens_descreve_aproximacao_parada_e_passagem():
    etapas = synthetic.roteiro(100, True)
    assert [(etapa.nome, etapa.porta, etapa.quantidade) for etapa in etapas] == [
        ("aproximação da antena 1", 1, 15),
        ("parado na antena 1", 1, 45),
        ("saída da antena 1", 1, 10),
        ("passagem pela antena 2", 2, 30),
    ]


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

    perfil = tmp_path / ".env.cloud.reader-01"
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


@pytest.mark.parametrize("progresso, conclui", [(True, True), (False, False)])
def test_verificador_aguarda_fila_lenta_mas_detecta_parada(monkeypatch, progresso, conclui):
    class Relogio:
        instante = 0.0

        def avancar(self, segundos):
            self.instante += segundos

    relogio = Relogio()

    class Conexao:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def scalar(self, _consulta, _parametros=None):
            return min(int(relogio.instante), 100 if progresso else 2)

    class Engine:
        def connect(self):
            return Conexao()

        def dispose(self):
            pass

    monkeypatch.setattr(verify, "create_engine", lambda *_args, **_kwargs: Engine())
    monkeypatch.setattr(verify.time, "monotonic", lambda: relogio.instante)
    monkeypatch.setattr(verify.time, "sleep", relogio.avancar)
    def executar():
        verify.conferir("db-local-de-teste", verify.Baseline(0, 0),
                        [synthetic.epcs_padrao(1)[0]],
                        passagem=False, mensagens=100, timeout=3)
    if conclui:
        executar()
        assert relogio.instante >= 100
    else:
        with pytest.raises(RuntimeError, match="sem progresso por 3s.*2/100"):
            executar()
        assert relogio.instante < 30


def test_verificador_usa_apenas_leituras_e_passagem_do_ensaio_atual(monkeypatch):
    class Resultado:
        def __init__(self, linha):
            self.linha = linha

        def one_or_none(self):
            return self.linha

    class Conexao:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def scalar(self, consulta, parametros):
            assert "timestamp_original" in str(consulta)
            assert parametros["contador_inicio"] == "1234567"
            assert parametros["contador_fim"] == "1234568"
            return 2

        def execute(self, consulta, parametros):
            if "FROM passagens p" in str(consulta):
                assert str(consulta).count("timestamp_original") == 2
                assert parametros["contador_inicio"] == "1234567"
                return Resultado(SimpleNamespace(id=7, direcao_status="confirmed",
                                                direcao="a_para_b", zona_destino_id=2))
            return Resultado(SimpleNamespace(id=8, equipamento_id=9,
                                            ultima_zona_id=2))

    class Engine:
        def connect(self):
            return Conexao()

        def dispose(self):
            pass

    monkeypatch.setattr(verify, "create_engine", lambda *_args, **_kwargs: Engine())
    verify.conferir("db-local-de-teste", verify.Baseline(0, 0),
                    [synthetic.epcs_padrao(1)[0]], passagem=True, mensagens=2,
                    contador_inicial=1_234_567)


def test_verificador_aguarda_fila_anterior_sem_conta_la_no_ensaio(monkeypatch):
    class Relogio:
        instante = 0.0

        def avancar(self, segundos):
            self.instante += segundos

    relogio = Relogio()

    class Conexao:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def scalar(self, consulta, _parametros=None):
            if "MAX(id)" in str(consulta):
                return int(relogio.instante)
            return max(0, min(10, int(relogio.instante) - 8))

    class Engine:
        def connect(self):
            return Conexao()

        def dispose(self):
            pass

    monkeypatch.setattr(verify, "create_engine", lambda *_args, **_kwargs: Engine())
    monkeypatch.setattr(verify.time, "monotonic", lambda: relogio.instante)
    monkeypatch.setattr(verify.time, "sleep", relogio.avancar)
    verify.conferir("db-local-de-teste", verify.Baseline(0, 0),
                    [synthetic.epcs_padrao(1)[0]], passagem=False, mensagens=10,
                    timeout=3, contador_inicial=1_234_567)
    assert relogio.instante >= 18


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
