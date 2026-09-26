"""Launcher interativo de testes RFID em Windows 11 e Ubuntu."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Annotated

import click
import typer
from dotenv import dotenv_values
from sqlalchemy.exc import SQLAlchemyError

from api.epc import normalizar_epc

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
from .synthetic import epcs_padrao, publicar, roteiro
from .terminals import abrir, encerrar
from .verify import conferir, inicio

app = typer.Typer(help="Prepara e observa um teste de laboratório RFID.")


def _escolher(valor: str | None, pergunta: str, opcoes: tuple[str, ...]) -> str:
    if valor is None:
        if not sys.stdin.isatty():
            raise ValueError(f"informe {pergunta} por flag em modo não interativo")
        valor = typer.prompt(f"{pergunta} ({'/'.join(opcoes)})", default=opcoes[0])
    if valor not in opcoes:
        raise ValueError(f"{pergunta}: escolha {' ou '.join(opcoes)}")
    return valor


def _cenario(env: str | None, source: str | None) -> tuple[str, str]:
    if env is None and source is None and sys.stdin.isatty():
        click.clear()
        typer.echo("1. Local com dados sintéticos")
        typer.echo("2. Local com leitor físico")
        typer.echo("3. Broker e banco externos com leitor físico")
        typer.echo("4. Broker e banco externos com dados sintéticos")
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


def _perfil_publicador(modo: str, valores: dict[str, str], arquivo: Path | None,
                      interativo: bool) -> dict[str, str]:
    if modo == "managed" and arquivo is None:
        padrao = ROOT / ".env.cloud.reader-01"
        if padrao.exists():
            arquivo = padrao
        elif interativo:
            arquivo = Path(typer.prompt("Arquivo da credencial MQTT de publicação",
                                       default=str(padrao)))
        else:
            raise ValueError("teste externo sintético exige --publisher-env-file com "
                             "credencial autorizada a publicar")
    if arquivo is None:
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
    return ", ".join(
        f"{item.name} (PID {item.pid or '?'}, porta(s) {','.join(map(str, item.ports))})"
        for item in bloqueios
    )


def _preparar_portas(binds: dict[int, str], projeto: str, force: bool,
                    interativo: bool) -> None:
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
    passage: Annotated[bool, typer.Option("--passage/--single")] = True,
    count: Annotated[int, typer.Option("--count", help="Quantidade de itens sintéticos")] = 1,
    messages: Annotated[int, typer.Option("--messages", help="Mensagens por item")] = 100,
    interval: Annotated[float, typer.Option("--interval")] = 0.5,
    epc: Annotated[list[str] | None, typer.Option("--epc")] = None,
) -> None:
    processos = []
    arquivo = None
    modo = None
    ambiente = None
    started = False
    marker = None
    lista: list[str] = []
    publisher: dict[str, str] | None = None
    etapa = "seleção do cenário"
    try:
        modo, origem = _cenario(env, source)
        print(f"Cenário: ambiente {modo}; origem {origem}; leitor {reader_id}")
        interativo = sys.stdin.isatty()
        if fresh and reuse:
            raise ValueError("escolha --fresh ou --reuse")
        if modo == "local" and not fresh and not reuse and interativo:
            fresh = not typer.confirm("Reaproveitar contêineres e dados existentes?", default=True)
        if modo == "managed" and fresh:
            raise ValueError("--fresh só é permitido no banco local")
        etapa = "configuração do ambiente"
        arquivo, valores = carregar(modo, env_file, interativo)
        ambiente = dict(os.environ, **valores)
        print(f"Configuração carregada de {arquivo.name}")
        if timestamp_format and timestamp_format not in ("counter", "rfc3339", "epoch_ms"):
            raise ValueError("--timestamp-format deve ser counter, rfc3339 ou epoch_ms")
        if origem == "synthetic":
            if timestamp_format not in (None, "counter"):
                raise ValueError("dados sintéticos reproduzem o timestamp counter do leitor")
            lista = [normalizar_epc(item) for item in (epc or epcs_padrao(count))]
            if len(set(lista)) != len(lista):
                raise ValueError("não repita o mesmo EPC no teste sintético")
            etapas = roteiro(messages, passage)
            print(f"Plano sintético: {len(lista)} item(ns), {messages} mensagens por item, "
                  f"total {len(lista) * messages}")
            for item in etapas:
                print(f"  {item.nome}: {item.quantidade} mensagem(ns)")
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
        migracao = "migrate-local" if modo == "local" else "migrate-managed"
        ingestor = "ingestor-local" if modo == "local" else "ingestor-managed"
        etapa = "build da imagem e migrations"
        print("Construindo imagem e aplicando migrations...")
        started = True
        compose(arquivo, modo, "up", "-d", "--build", migracao, env=ambiente,
                mostrar=True)
        etapa = "conclusão das migrations"
        aguardar(arquivo, modo, migracao, completo=True, env=ambiente)
        etapa = "cadastro base do laboratório"
        print("Garantindo cadastro base...")
        seed_env = dict(ambiente)
        if modo == "managed":
            seed_env["DATABASE_URL"] = valores["DATABASE_URL"]
        executar([sys.executable, "-m", "tools.lab_launcher.seed", "--reader-id", reader_id,
                  *(["--serial", serial] if serial else []),
                  *(item for valor in lista for item in ("--epc", valor))],
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
            etapa = "publicação das leituras sintéticas"
            assert publisher is not None
            baseline = inicio(valores["APP_DATABASE_URL"])
            total = publicar(publisher, reader_id, epcs=lista, passagem=passage,
                             intervalo=interval, portal_id=portal_id,
                             mensagens=messages,
                             timestamp_format=ambiente["EZ700_TIMESTAMP_FORMAT"])
            print(f"{total} leitura(s) sintética(s) publicada(s)")
            etapa = "verificação da Sprint 2 no banco"
            conferir(valores["APP_DATABASE_URL"], baseline, lista,
                     passagem=passage, mensagens=messages)
        else:
            print("Pronto para leituras do leitor físico. Use 'stop' ao encerrar.")
        if interativo and not no_terminals:
            print("Acompanhando o teste. Pressione Ctrl+C para encerrar os serviços.")
            while marker is not None and marker.exists():
                time.sleep(1)
    except (KeyboardInterrupt, click.Abort):
        parar_sessao()
        encerrar(processos)
        if started and arquivo is not None and modo is not None and ambiente is not None:
            compose(arquivo, modo, "down", env=ambiente)
        print("Teste encerrado")
    except (ValueError, RuntimeError, TimeoutError, OSError, SQLAlchemyError) as erro:
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
    if env not in ("local", "managed") or (env == "managed" and (volumes or clear_ports)):
        raise typer.BadParameter("--volumes e --clear-ports só são permitidos no modo local")
    if volumes and not force and not typer.confirm("Apagar volumes locais definitivamente?",
                                                   default=False):
        raise typer.Exit()
    arquivo = env_file or ROOT / (".env.local" if env == "local" else ".env.cloud")
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
