"""Launcher interativo de testes RFID em Windows 11 e Ubuntu."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

import click
import typer
from dotenv import dotenv_values
from sqlalchemy.exc import SQLAlchemyError

from rfid_ingestion.topics import reading_topic

from . import bridge
from .config import ROOT, carregar
from .docker_env import (
    _limpar_saida,
    aguardar,
    compose,
    conflitos,
    encerrar_processos,
    executar,
    porta_disponivel,
    portas_do_projeto,
    processos_nas_portas,
)
from .session import iniciar as iniciar_sessao
from .session import parar as parar_sessao
from .tags import epcs_recentes, parse_tag, perguntar_tags
from .terminals import abrir, encerrar

app = typer.Typer(help="Prepara e observa um teste de laboratório RFID.")


def _escolher(valor: str | None, pergunta: str, opcoes: tuple[str, ...]) -> str:
    """Solicita uma escolha apenas quando ausente e valida contra as opções do menu."""
    if valor is None:
        if not sys.stdin.isatty():
            raise ValueError(f"informe {pergunta} por flag em modo não interativo")
        valor = typer.prompt(f"{pergunta} ({'/'.join(opcoes)})", default=opcoes[0])
    if valor not in opcoes:
        raise ValueError(f"{pergunta}: escolha {' ou '.join(opcoes)}")
    return valor


def _cenario(env: str | None, source: str | None) -> tuple[str, str]:
    """Resolve ambiente local/externo e origem física/sintética do menu ou dos argumentos."""
    if env is None and source is None and sys.stdin.isatty():
        click.clear()
        typer.echo("1. Local com simulador visual (dados sintéticos)")
        typer.echo("2. Local com leitor físico")
        typer.echo("3. Broker e banco externos com leitor físico")
        typer.echo("4. Broker e banco externos com simulador visual (dados sintéticos)")
        escolha = typer.prompt("Escolha o teste (1-4)", default="1")
        cenarios = {
            "1": ("local", "synthetic"),
            "2": ("local", "physical"),
            "3": ("managed", "physical"),
            "4": ("managed", "synthetic"),
        }
        if escolha not in cenarios:
            raise ValueError("escolha um teste de 1 a 4")
        return cenarios[escolha]
    return (
        _escolher(env, "Ambiente", ("local", "managed")),
        _escolher(source, "Origem", ("physical", "synthetic")),
    )


def _transporte_escolhido(valor: str | None, modo: str, interativo: bool) -> str:
    """Resolve a escolha entre MQTT com TLS, sem TLS (laboratório) e bridge local com TLS."""
    if modo != "managed":
        if valor not in (None, "tls"):
            raise ValueError("--mqtt-transport só se aplica ao broker externo")
        return "tls"
    if valor is None and interativo:
        typer.echo("Transporte MQTT do broker externo:")
        typer.echo("1. mqtts com TLS (porta 8883, HiveMQ Cloud)")
        typer.echo("2. mqtt sem TLS (porta 1883, somente para ensaio de laboratório)")
        typer.echo("3. bridge: leitor em mqtt sem TLS no notebook, repassado ao HiveMQ "
                   "Cloud com TLS (leitor físico)")
        valor = {"1": "tls", "2": "plain", "3": "bridge"}.get(
            typer.prompt("Escolha o transporte (1-3)", default="1"), "")
    valor = valor or "tls"
    if valor not in ("tls", "plain", "bridge"):
        raise ValueError("--mqtt-transport deve ser tls, plain ou bridge")
    return valor


def _avisar_transporte_plain(valores: dict[str, str], interativo: bool) -> None:
    """Apresenta as condições do transporte sem TLS selecionado para o laboratório."""
    host = valores["MQTT_HOST"]
    print(f"ATENÇÃO: MQTT sem TLS em {host}:{valores['MQTT_PORT']}. Leituras trafegam "
          "em texto aberto; use apenas EPCs de laboratório.")
    if host.endswith(".hivemq.cloud"):
        aviso = ("clusters HiveMQ Cloud aceitam somente TLS (8883) ou WebSocket TLS "
                 "(8884); a porta 1883 deve ser recusada")
        if not interativo or not typer.confirm(f"{aviso}. Continuar mesmo assim?",
                                               default=False):
            raise ValueError(aviso)


def _tags_fisicas(tags: list[str] | None, database_url: str,
                  interativo: bool) -> list[tuple[str, str]]:
    """Obtém tags e nomes por argumentos ou consulta interativa dos EPCs recentes."""
    if tags:
        escolhidas = dict(parse_tag(item) for item in tags)
        return list(escolhidas.items())
    if not interativo:
        print("Nenhuma --tag informada; nenhum equipamento será cadastrado.")
        return []
    try:
        recentes = epcs_recentes(database_url)
    except SQLAlchemyError:
        recentes = []
    return perguntar_tags(recentes)


def _perfil_publicador(modo: str, valores: dict[str, str], arquivo: Path | None,
                      interativo: bool) -> dict[str, str]:
    """Carrega credencial com permissão de publicação separada da assinatura do ingestor."""
    if modo == "managed" and arquivo is None and valores.get("MQTT_INSECURE_LAB") != "true":
        padrao = ROOT / "config" / "environments" / ".env.cloud.reader-01"
        if padrao.exists():
            arquivo = padrao
        elif interativo:
            arquivo = Path(typer.prompt("Arquivo da credencial MQTT de publicação",
                                       default=str(padrao)))
        else:
            raise ValueError("teste externo sintético exige --publisher-env-file com "
                             "credencial autorizada a publicar")
    if arquivo is None or valores.get("MQTT_INSECURE_LAB") == "true":
        return dict(valores)
    if not arquivo.is_file():
        raise ValueError(f"arquivo do publicador ausente: {arquivo}")
    perfil = {chave: valor for chave, valor in dotenv_values(arquivo).items()
              if valor is not None and chave.startswith("MQTT_")}
    if modo == "managed":
        if not perfil.get("MQTT_USERNAME") or not perfil.get("MQTT_PASSWORD"):
            raise ValueError("perfil do publicador exige MQTT_USERNAME e MQTT_PASSWORD")
        if perfil["MQTT_USERNAME"] == valores.get("MQTT_USERNAME"):
            raise ValueError("use uma credencial MQTT de publicação separada do ingestor")
        if not perfil.get("MQTT_TOPIC") or any(
            coringa in perfil["MQTT_TOPIC"] for coringa in ("+", "#")
        ):
            raise ValueError("perfil do publicador exige MQTT_TOPIC exato, sem curingas")
    print(f"Perfil MQTT de publicação: {arquivo.name}")
    return dict(valores, **perfil)


def _descricao_bloqueios(bloqueios) -> str:
    """Formata nomes, PIDs e portas dos processos que impedem o início do ensaio."""
    return ", ".join(
        f"{item.name} (PID {item.pid or '?'}, porta(s) {','.join(map(str, item.ports))})"
        for item in bloqueios
    )


def _preparar_portas(binds: dict[int, str], projeto: str, force: bool,
                    interativo: bool) -> None:
    """Detecta conflitos de serviços/processos e solicita resolução antes de iniciar o ensaio."""
    portas = tuple(binds)
    achados = conflitos(portas, projeto)
    if achados:
        nomes = ", ".join(nome for _, nome in achados)
        if not force and (not interativo or not typer.confirm(
            f"Remover contêineres que ocupam as portas locais: {nomes}?", default=False
        )):
            raise ValueError(f"portas locais ocupadas por contêineres: {nomes}")
        print("Removendo contêineres conflitantes...")
        for cid, _ in achados:
            executar(["docker", "rm", "-f", cid])

    for _ in range(5 if achados else 1):
        bloqueios = processos_nas_portas(portas, portas_do_projeto(portas, projeto))
        if not bloqueios:
            break
        time.sleep(1)
    if bloqueios:
        descricao = _descricao_bloqueios(bloqueios)
        if not force and (not interativo or not typer.confirm(
            f"Encerrar processos que ocupam as portas locais: {descricao}?", default=False
        )):
            raise ValueError(f"portas locais ocupadas por processos: {descricao}")
        print("Encerrando processos que ocupam as portas locais...")
        encerrar_processos(bloqueios)
    proprias = portas_do_projeto(portas, projeto)
    if processos_nas_portas(portas, proprias):
        raise RuntimeError("portas locais continuam ocupadas após o encerramento")
    indisponiveis = [porta for porta, endereco in binds.items()
                     if porta not in proprias and not porta_disponivel(endereco, porta)]
    if indisponiveis:
        raise RuntimeError("portas TCP ainda indisponíveis: " + ", ".join(map(str, indisponiveis)))


def _fechar_simulador(simulador: subprocess.Popen | None) -> None:
    # Separado de ``encerrar``: no Windows ele preserva as janelas dos observadores.
    """Encerra o subprocesso do simulador se ainda estiver em execução."""
    if simulador is not None and simulador.poll() is None:
        simulador.terminate()


@app.command()
def start(
    env: Annotated[str | None, typer.Option("--env", help="local ou managed")] = None,
    source: Annotated[str | None, typer.Option("--source", help="physical ou synthetic")] = None,
    env_file: Annotated[Path | None, typer.Option("--env-file")] = None,
    publisher_env_file: Annotated[Path | None, typer.Option("--publisher-env-file")] = None,
    fresh: Annotated[bool, typer.Option("--fresh", help="Apaga volumes locais antes do teste")] = False,
    reuse: Annotated[bool, typer.Option("--reuse", help="Reaproveita dados sem perguntar")] = False,
    force: Annotated[bool, typer.Option("--force", help="Remove bloqueios de porta sem perguntar")] = False,
    no_terminals: Annotated[bool, typer.Option("--no-terminals")] = False,
    reader_id: Annotated[str, typer.Option("--reader-id")] = "reader-01",
    portal_id: Annotated[str, typer.Option("--portal-id")] = "portal-01",
    serial: Annotated[str | None, typer.Option("--serial")] = None,
    timestamp_format: Annotated[str | None, typer.Option("--timestamp-format")] = None,
    tag: Annotated[list[str] | None, typer.Option(
        "--tag", help="Leitor físico: EPC=Nome do equipamento (repita por tag)")] = None,
    mqtt_transport: Annotated[str | None, typer.Option(
        "--mqtt-transport",
        help="Broker externo: tls (8883), plain (1883, laboratório) ou bridge "
             "(leitor sem TLS no notebook → HiveMQ Cloud com TLS)")] = None,
) -> None:
    """Prepara perfil e portas, sobe infraestrutura/migrations, semeia o domínio e inicia o ensaio.

    Pode abrir observadores e simulador. Limpeza de volumes pertence apenas ao
    modo local e depende da escolha explícita; falhas encerram serviços iniciados."""
    processos = []
    arquivo = None
    modo = None
    ambiente = None
    started = False
    marker = None
    tags_fisicas: list[tuple[str, str]] = []
    publisher: dict[str, str] | None = None
    simulador: subprocess.Popen | None = None
    etapa = "seleção do cenário"
    try:
        modo, origem = _cenario(env, source)
        print(f"Cenário: ambiente {modo}; origem {origem}; leitor {reader_id}")
        interativo = sys.stdin.isatty()
        if origem == "synthetic" and tag:
            raise ValueError("--tag é do leitor físico; no simulador os nomes são "
                             "definidos na janela")
        if origem == "synthetic" and importlib.util.find_spec("flet") is None:
            raise ValueError("simulador visual exige Flet: pip install -r "
                             "requirements/lab.txt")
        if fresh and reuse:
            raise ValueError("escolha --fresh ou --reuse")
        if modo == "local" and not fresh and not reuse and interativo:
            fresh = not typer.confirm("Reaproveitar contêineres e dados existentes?", default=True)
        if modo == "managed" and fresh:
            raise ValueError("--fresh só é permitido no banco local")
        etapa = "configuração do ambiente"
        transporte = _transporte_escolhido(mqtt_transport, modo, interativo)
        if transporte == "bridge" and origem != "physical":
            raise ValueError("a bridge é para o leitor físico; o simulador publica "
                             "direto no HiveMQ Cloud com TLS")
        arquivo, valores = carregar(modo, env_file, interativo, transporte)
        if transporte == "plain":
            _avisar_transporte_plain(valores, interativo)
        ambiente = dict(os.environ, **valores)
        if transporte == "bridge":
            ambiente.update(bridge.perfil_bridge(
                reader_id, reading_topic(reader_id, portal=portal_id), valores,
                publisher_env_file))
        print(f"Configuração carregada de {arquivo.name}")
        if modo == "managed":
            print(f"Broker externo: {valores['MQTT_HOST']}:{valores.get('MQTT_PORT', '8883')} "
                  f"({'mqtt sem TLS' if transporte == 'plain' else 'mqtts/TLS'}"
                  f"{'; leitor via bridge local sem TLS' if transporte == 'bridge' else ''}); "
                  f"tópico {valores.get('MQTT_TOPIC', 'easy/dev/hupaa/+/+/readings')}")
        if timestamp_format and timestamp_format not in ("counter", "rfc3339", "epoch_ms"):
            raise ValueError("--timestamp-format deve ser counter, rfc3339 ou epoch_ms")
        if origem == "synthetic":
            if timestamp_format not in (None, "counter"):
                raise ValueError("dados sintéticos reproduzem o timestamp counter do leitor")
            publisher = _perfil_publicador(modo, valores, publisher_env_file,
                                           interativo)
        ambiente["EZ700_TIMESTAMP_FORMAT"] = timestamp_format or "counter"
        projeto = valores.get("COMPOSE_PROJECT_NAME", "rfid-hospital-local" if modo == "local"
                              else "rfid-hospital-managed")
        if fresh:
            etapa = "limpeza dos volumes locais"
            print("Removendo ambiente local e volumes...")
            compose(arquivo, modo, "down", "-v", env=ambiente, mostrar=True)
        if modo == "local":
            etapa = "verificação das portas TCP"
            portas = (int(valores.get("POSTGRES_PORT", "5432")),
                      int(valores.get("MQTT_LOCAL_PORT", "1883")))
            if portas[0] == portas[1]:
                raise ValueError("PostgreSQL e MQTT locais não podem usar a mesma porta")
            binds = {
                portas[0]: valores.get("POSTGRES_BIND_ADDRESS", "127.0.0.1"),
                portas[1]: valores.get("MQTT_BIND_ADDRESS", "0.0.0.0"),
            }
            print("Verificando as portas TCP locais...")
            _preparar_portas(binds, projeto, force, interativo)
            print("Iniciando PostgreSQL e Mosquitto locais...")
            etapa = "inicialização do PostgreSQL e Mosquitto"
            started = True
            compose(arquivo, modo, "up", "-d", "postgres", "mosquitto", env=ambiente,
                    mostrar=True)
            for servico in ("postgres", "mosquitto"):
                etapa = f"saúde do {servico}"
                print(f"Aguardando {servico} saudável...")
                aguardar(arquivo, modo, servico, env=ambiente)
        if transporte == "bridge":
            etapa = "verificação da porta MQTT local"
            porta = int(valores.get("MQTT_LOCAL_PORT", "1883"))
            print("Verificando a porta MQTT local da bridge...")
            _preparar_portas({porta: valores.get("MQTT_BIND_ADDRESS", "0.0.0.0")},
                             projeto, force, interativo)
            etapa = "inicialização da bridge MQTT"
            print("Iniciando a bridge MQTT local → HiveMQ Cloud...")
            started = True
            compose(arquivo, modo, "up", "-d", bridge.SERVICO, env=ambiente, mostrar=True)
            aguardar(arquivo, modo, bridge.SERVICO, env=ambiente)
            etapa = "conexão da bridge ao HiveMQ Cloud"
            bridge.aguardar_conexao(arquivo, ambiente)
            print("Bridge conectada ao HiveMQ Cloud")
        migracao = "migrate-local" if modo == "local" else "migrate-managed"
        ingestor = "ingestor-local" if modo == "local" else "ingestor-managed"
        etapa = "build da imagem e migrations"
        print("Construindo imagem e aplicando migrations...")
        started = True
        compose(arquivo, modo, "up", "-d", "--build", migracao, env=ambiente,
                mostrar=True)
        etapa = "conclusão das migrations"
        aguardar(arquivo, modo, migracao, completo=True, env=ambiente)
        if origem == "physical":
            etapa = "seleção das tags físicas"
            tags_fisicas = _tags_fisicas(tag, valores["APP_DATABASE_URL"], interativo)
        etapa = "cadastro base do laboratório"
        print("Garantindo cadastro base...")
        seed_env = dict(ambiente)
        if modo == "managed":
            seed_env["DATABASE_URL"] = valores["DATABASE_URL"]
        executar([sys.executable, "-m", "tools.lab_launcher.seed", "--reader-id", reader_id,
                  *(["--serial", serial] if serial else []),
                  *(item for par in tags_fisicas for item in ("--tag", "=".join(par)))],
                 env=seed_env, mostrar=True)
        etapa = "inicialização do ingestor"
        print("Iniciando ingestor...")
        compose(arquivo, modo, "up", "-d", ingestor, env=ambiente, mostrar=True)
        etapa = "saúde do ingestor"
        aguardar(arquivo, modo, ingestor, env=ambiente)
        if not no_terminals:
            etapa = "abertura dos terminais de observação"
            print("Abrindo observação MQTT, ingestor e banco...")
            marker = iniciar_sessao()
            processos = abrir(arquivo, modo, ingestor, ambiente, marker)
        if origem == "synthetic":
            etapa = "abertura do simulador visual"
            assert publisher is not None
            print("Abrindo o simulador visual do laboratório...")
            # Credencial de publicação sobre o ambiente; banco do seed para o cadastro.
            ambiente_simulador = {**ambiente, **publisher,
                                  "DATABASE_URL": seed_env["DATABASE_URL"]}
            simulador = subprocess.Popen(
                [sys.executable, "-m", "tools.lab_simulator", "--reader-id", reader_id,
                 "--portal-id", portal_id],
                cwd=ROOT, env=ambiente_simulador)
            processos.append(simulador)
            print("Defina os itens na janela e arraste-os até as antenas. Use Ctrl+C "
                  "para encerrar o teste.")
        else:
            if tags_fisicas:
                print("Equipamentos do ensaio:")
                for valor, nome in tags_fisicas:
                    print(f"  {valor} → {nome}")
            topico = reading_topic(reader_id, portal=portal_id)
            if transporte == "bridge":
                print(f"Configure o leitor: URL mqtt://{bridge.ip_local()}, porta "
                      f"{valores.get('MQTT_LOCAL_PORT', '1883')}, usuário e senha vazios, "
                      f"tópico {topico}. A bridge repassa as leituras ao HiveMQ Cloud.")
            print(f"Pronto para leituras do leitor físico em {valores['MQTT_HOST']}:"
                  f"{valores.get('MQTT_PORT')} no tópico {topico}. Use 'stop' ao encerrar.")
        if interativo and not no_terminals:
            print("Acompanhando o teste. Pressione Ctrl+C para encerrar os serviços.")
            while marker is not None and marker.exists():
                time.sleep(1)
        elif simulador is not None:
            simulador.wait()
    except (KeyboardInterrupt, click.Abort):
        _fechar_simulador(simulador)
        parar_sessao()
        encerrar(processos)
        if started and arquivo is not None and modo is not None and ambiente is not None:
            compose(arquivo, modo, "down", env=ambiente)
        print("Teste encerrado")
    except (ValueError, RuntimeError, TimeoutError, OSError, SQLAlchemyError) as erro:
        _fechar_simulador(simulador)
        if marker is not None:
            parar_sessao()
        if started and arquivo is not None and modo is not None and ambiente is not None:
            try:
                compose(arquivo, modo, "down", env=ambiente)
            except (OSError, RuntimeError):
                pass
        detalhe = _limpar_saida(str(erro), ambiente)
        typer.echo(f"Falha na etapa '{etapa}': {detalhe}", err=True)
        raise typer.Exit(1) from None


@app.command()
def stop(
    env: Annotated[str, typer.Option("--env")] = "local",
    env_file: Annotated[Path | None, typer.Option("--env-file")] = None,
    volumes: Annotated[bool, typer.Option("--volumes", help="Apaga dados locais")] = False,
    force: Annotated[bool, typer.Option("--force", help="Dispensa confirmação de --volumes")] = False,
    clear_ports: Annotated[bool, typer.Option("--clear-ports",
                                                help="Encerra também processos nas portas locais")] = False,
) -> None:
    """Sinaliza observadores e encerra o Compose do perfil escolhido; volumes exigem opção explícita."""
    if env not in ("local", "managed") or (env == "managed" and (volumes or clear_ports)):
        raise typer.BadParameter("--volumes e --clear-ports só são permitidos no modo local")
    if volumes and not force and not typer.confirm("Apagar volumes locais definitivamente?",
                                                   default=False):
        raise typer.Exit()
    arquivo = env_file or ROOT / "config" / "environments" / (".env.local" if env == "local" else ".env.cloud")
    if not arquivo.exists():
        raise typer.BadParameter(f"arquivo de ambiente ausente: {arquivo}")
    valores = {k: v for k, v in dotenv_values(arquivo).items() if v is not None}
    parar_sessao()
    try:
        print("Encerrando serviços Compose...")
        compose(arquivo, env, "down", *(["-v"] if volumes else []),
                env=dict(os.environ, **valores), mostrar=True)
    except (OSError, RuntimeError) as erro:
        typer.echo("Falha ao encerrar os serviços Compose: "
                   + _limpar_saida(str(erro), valores), err=True)
        raise typer.Exit(1) from None
    if env == "local":
        portas = (int(valores.get("POSTGRES_PORT", "5432")),
                  int(valores.get("MQTT_LOCAL_PORT", "1883")))
        binds = {
            portas[0]: valores.get("POSTGRES_BIND_ADDRESS", "127.0.0.1"),
            portas[1]: valores.get("MQTT_BIND_ADDRESS", "0.0.0.0"),
        }
        for _ in range(5):
            bloqueios = processos_nas_portas(portas)
            if not bloqueios and all(porta_disponivel(endereco, porta)
                                     for porta, endereco in binds.items()):
                break
            time.sleep(1)
        if bloqueios and (clear_ports or (sys.stdin.isatty() and typer.confirm(
            f"Portas ainda ocupadas por {_descricao_bloqueios(bloqueios)}. Encerrar?",
            default=False,
        ))):
            try:
                encerrar_processos(bloqueios)
            except RuntimeError as erro:
                typer.echo(str(erro), err=True)
                raise typer.Exit(1) from None
            bloqueios = processos_nas_portas(portas)
        indisponiveis = [porta for porta, endereco in binds.items()
                         if not porta_disponivel(endereco, porta)]
        if bloqueios or indisponiveis:
            if bloqueios:
                print(f"Portas ainda ocupadas: {_descricao_bloqueios(bloqueios)}")
            if indisponiveis:
                print("Portas TCP indisponíveis: " + ", ".join(map(str, indisponiveis)))
        else:
            print("Portas locais livres")
    print("Ambiente encerrado")


if __name__ == "__main__":
    app()
