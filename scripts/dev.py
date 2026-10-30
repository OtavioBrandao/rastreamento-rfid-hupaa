"""Sobe API + frontend e abre o launcher de laboratório em um só comando.

Uso (na raiz do repositório, em Windows 11 ou Ubuntu 24.04):

    python scripts/dev.py              # mostra o menu de testes 1-4
    python scripts/dev.py --teste 4    # escolhe direto, sem menu
    python scripts/dev.py --sem-teste  # só API e frontend, no banco externo

Fluxo:
1. Mostra o mesmo menu do ``python -m tools.lab_launcher`` (1 a 4).
2. Sobe a API FastAPI apontando para o banco do teste escolhido (local ou
   externo) e o frontend Vite, em segundo plano, e abre o navegador.
3. Entrega o terminal ao launcher, que segue com as perguntas dele, sobe o
   backend em Docker, abre os três terminais de observação (MQTT, Ingestor e
   Banco). Nas opções 1 e 4 a API sobe com o simulador web habilitado e o
   navegador abre em ``#/simulador`` (planta EASY ou HUPAA); o controle dos
   equipamentos fica num link próprio, em outra aba. Não há aplicativo desktop.

Ctrl+C encerra o launcher (que derruba os contêineres) e depois a API e o
frontend. A saída da API e do frontend vai para ``data/dev/*.log`` para não
se misturar às perguntas do launcher. Nenhuma credencial é exibida nem passada
na linha de comando: a API lê o mesmo arquivo de ambiente que o launcher.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
LOGS = ROOT / "data" / "dev"
WINDOWS = os.name == "nt"
PASTAS_BACKEND = ("api", "db", "rfid_inference", "rfid_ingestion", "rfid_location", "rfid_movement")

TESTES = {
    "1": ("local", "synthetic", "Local com simulador web (dados sintéticos)"),
    "2": ("local", "physical", "Local com leitor físico"),
    "3": ("managed", "physical", "Broker e banco externos com leitor físico"),
    "4": ("managed", "synthetic", "Broker e banco externos com simulador web (dados sintéticos)"),
}


def python_do_projeto() -> str:
    """Seleciona o Python da .venv local ou usa o executável que iniciou o comando."""
    for candidato in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if candidato.exists():
            return str(candidato)
    return sys.executable


def ambiente_simulador(modo: str, valores: dict[str, str]) -> dict[str, str]:
    """Variáveis do simulador web na API: local usa o Mosquitto do ensaio; externo,
    a credencial de PUBLICAÇÃO de ``.env.cloud.reader-01`` (nunca a do ingestor)."""
    extras = {"SIMULADOR_HABILITADO": "true", "APP_ENV": valores.get("APP_ENV") or "development",
              "SIMULADOR_TOPICO_INGESTOR": valores.get("MQTT_TOPIC") or "easy/dev/hupaa/+/+/readings"}
    if modo == "local":
        # Sobrepõe também eventuais variáveis SIMULADOR_MQTT_* externas do shell/perfil.
        extras.update({"SIMULADOR_MQTT_MODE": "local", "SIMULADOR_MQTT_HOST": "127.0.0.1",
                       "SIMULADOR_MQTT_PORT": valores.get("MQTT_LOCAL_PORT", "1883"),
                       "SIMULADOR_MQTT_TLS_ENABLED": "false", "SIMULADOR_MQTT_INSECURE_LAB": "false",
                       "SIMULADOR_MQTT_USERNAME": "", "SIMULADOR_MQTT_PASSWORD": "",
                       "SIMULADOR_MQTT_CA_CERT": "", "SIMULADOR_MQTT_TOPICO_RELAY": "",
                       "SIMULADOR_MQTT_TOPICO_PERMITIDO": ""})
    if modo == "managed" and valores.get("MQTT_INSECURE_LAB") != "true":
        from tools.lab_launcher.cli import _perfil_publicador

        try:
            perfil = _perfil_publicador(modo, valores, None, False)
        except ValueError as erro:
            print(f"Simulador web desabilitado: {erro}", flush=True)
            return {"SIMULADOR_HABILITADO": "false"}
        extras.update({f"SIMULADOR_{chave}": valor for chave, valor in perfil.items()
                       if chave in ("MQTT_USERNAME", "MQTT_PASSWORD", "MQTT_CA_CERT")})
        # Perfil com tópico exato (ACL de um leitor só, como o simulador Flet usava):
        # os leitores virtuais publicam por ele (relay) e o ingestor do ensaio aceita
        # `sim_reader_id` só desse tópico. Filtro com `+` vira só checagem local.
        topico = perfil.get("MQTT_TOPIC", "")
        if "+" in topico:
            extras["SIMULADOR_MQTT_TOPICO_PERMITIDO"] = topico
        elif topico:
            extras["SIMULADOR_MQTT_TOPICO_RELAY"] = topico
    return extras


def migracao_pendente() -> tuple[str, str] | None:
    """Compara a revisão do banco com a head do Alembic; devolve (banco, head) se diferem."""
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError

    from db.url import get_database_url

    head = ScriptDirectory.from_config(Config(str(ROOT / "config" / "alembic.ini"))).get_current_head()
    engine = create_engine(get_database_url())
    try:
        with engine.connect() as conexao:
            atual = MigrationContext.configure(conexao).get_current_revision()
    except OperationalError:
        # No modo local o Postgres do Docker só sobe depois, pelo launcher.
        return None
    finally:
        engine.dispose()
    return None if atual == head else (atual or "vazia", head or "?")


def servir_api(modo: str, env_file: str | None, host: str, porta: int,
               simulador: bool = False) -> None:
    """Roda no Python da .venv: resolve o banco como o launcher e inicia o uvicorn."""
    sys.path.insert(0, str(ROOT))
    from watchfiles import PythonFilter, watch

    from tools.lab_launcher.config import carregar

    _, valores = carregar(modo, Path(env_file) if env_file else None, interativo=False)
    os.environ.update(valores)
    pendente = migracao_pendente()
    if pendente:
        # Banco atrás do código quebra rotas novas com 500; nunca migra sozinho
        # (o banco externo é compartilhado), só para e diz o comando.
        sys.exit(f"Banco na migration {pendente[0]}, código em {pendente[1]}. Aplique antes:\n"
                 f"  python -m alembic -c config/alembic.ini upgrade head  (com DATABASE_URL do {modo})")
    if simulador:
        os.environ.update(ambiente_simulador(modo, valores))
        # Uma marca por execução: a API restaura a demonstração padrão do HU só na
        # primeira subida; as recargas automáticas desta execução não a repetem.
        os.environ.setdefault("SIMULADOR_DEMO_EXECUCAO", f"{int(time.time())}-{os.getpid()}")
    # Recarrega ao salvar código do backend (o frontend já recarrega pelo Vite).
    # Não usa o `reload=True` do uvicorn: no Windows ele reinicia mandando Ctrl+C,
    # que este processo (grupo próprio, ver `iniciar`) ignora, e a API antiga fica
    # no ar com o código velho. Aqui a árvore do uvicorn é derrubada e sobe de novo.
    comando = [sys.executable, "-m", "uvicorn", "api.main:app", "--host", host, "--port", str(porta)]
    processo = subprocess.Popen(comando, cwd=ROOT)
    try:
        # Acorda a cada 2 s mesmo sem mudança: se a API caiu (ex.: porta ainda ocupada
        # por um processo antigo), sobe de novo em vez de deixar o site sem API.
        for mudancas in watch(*(ROOT / pasta for pasta in PASTAS_BACKEND), watch_filter=PythonFilter(),
                              rust_timeout=2000, yield_on_timeout=True):
            if not mudancas:
                if processo.poll() is not None:
                    print(f"A API parou (código {processo.returncode}); subindo de novo...", flush=True)
                    processo = subprocess.Popen(comando, cwd=ROOT)
                continue
            nomes = sorted({Path(caminho).relative_to(ROOT).as_posix() for _, caminho in mudancas})
            print(f"Código alterado ({', '.join(nomes)}): reiniciando a API...", flush=True)
            encerrar(processo)
            processo.wait()
            processo = subprocess.Popen(comando, cwd=ROOT)
    finally:
        encerrar(processo)


def escolher_teste(valor: str | None) -> str:
    # Mesmo menu do tools.lab_launcher; aqui só para saber qual banco a API deve usar.
    """Resolve uma das quatro opções do menu de demonstração."""
    if valor is None:
        for chave, (_, _, descricao) in TESTES.items():
            print(f"{chave}. {descricao}")
        valor = input("Escolha o teste (1-4) [1]: ").strip() or "1"
    if valor not in TESTES:
        sys.exit("Escolha um teste de 1 a 4.")
    return valor


def porta_ocupada(host: str, porta: int) -> bool:
    """Testa conexão TCP para detectar um listener existente antes de iniciar API/interface."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, porta)) == 0


def aguardar_http(url: str, processo: subprocess.Popen, timeout: float = 30) -> bool:
    """Aguarda resposta HTTP enquanto o subprocesso está vivo, respeitando timeout."""
    # As sondas locais não passam por um proxy externo herdado do shell.
    local = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    prazo = time.monotonic() + timeout
    while time.monotonic() < prazo and processo.poll() is None:
        try:
            with local.open(url, timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def iniciar(comando: list[str], pasta: Path, env: dict[str, str], log: Path | None) -> subprocess.Popen:
    # Grupo próprio: o Ctrl+C do terminal vai só para o launcher; estes são encerrados depois.
    """Inicia subprocesso em grupo próprio, com entrada fechada e log opcional."""
    extras = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS
              else {"start_new_session": True})
    saida = open(log, "w", encoding="utf-8") if log else None  # noqa: SIM115 - vive junto do processo
    return subprocess.Popen(comando, cwd=pasta, env=env, stdin=subprocess.DEVNULL,
                            stdout=saida, stderr=subprocess.STDOUT if saida else None, **extras)


def encerrar(processo: subprocess.Popen) -> None:
    """Fecha a vigência da associação ativa no instante informado."""
    if processo.poll() is not None:
        return
    if WINDOWS:
        # npm.cmd abre node como filho; /T derruba a árvore inteira.
        subprocess.run(["taskkill", "/PID", str(processo.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return
    try:
        os.killpg(processo.pid, signal.SIGTERM)
        processo.wait(timeout=8)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        os.killpg(processo.pid, signal.SIGKILL)


def ultimas_linhas(log: Path | None, quantidade: int = 15) -> str:
    """Lê o fim do log de um subprocesso para diagnóstico de inicialização."""
    if log is None or not log.exists():
        return ""
    return "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-quantidade:])


def preparar_frontend(npm: str, offline: bool) -> None:
    """No teste 1 exige Vite instalado; os demais modos mantêm a instalação automática."""
    if offline:
        if not (FRONTEND / "node_modules" / "vite" / "bin" / "vite.js").is_file():
            sys.exit("Teste 1 offline: dependências do frontend ausentes. Antes da demonstração, "
                     "execute npm --prefix frontend ci. Nenhum download foi tentado.")
    elif not (FRONTEND / "node_modules").exists():
        print("Instalando dependências do frontend (npm ci)...", flush=True)
        subprocess.run([npm, "ci"], cwd=FRONTEND, check=True)


def main() -> int:
    """Executa a entrada de linha de comando de scripts.dev; devolve o código de saída quando aplicável."""
    parser = argparse.ArgumentParser(description="Sobe API + frontend e abre o launcher de laboratório.")
    parser.add_argument("--teste", choices=sorted(TESTES), help="pula o menu e escolhe o teste")
    parser.add_argument("--sem-teste", action="store_true",
                        help="sobe só API e frontend no banco externo, sem o launcher")
    parser.add_argument("--env-file", help="arquivo de ambiente (padrão: config/environments/.env.local ou .env.cloud)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, default=8010)
    parser.add_argument("--front-port", type=int, default=5173)
    parser.add_argument("--sem-navegador", action="store_true", help="não abre o navegador")
    parser.add_argument("--reaproveitar", action="store_true",
                        help="modo local: reaproveita contêineres e dados sem perguntar")
    parser.add_argument("--mqtt-transport", choices=("tls", "plain"),
                        help="repassa ao launcher (broker externo) e pula a pergunta do transporte")
    parser.add_argument("--servir-api", choices=("local", "managed"), help=argparse.SUPPRESS)
    parser.add_argument("--com-simulador", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.servir_api:
        servir_api(args.servir_api, args.env_file, args.host, args.api_port, args.com_simulador)
        return 0

    for fluxo in (sys.stdout, sys.stderr):
        fluxo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    python = python_do_projeto()
    if args.sem_teste:
        modo, origem = "managed", None
    else:
        modo, origem, descricao = TESTES[escolher_teste(args.teste)]
        print(f"\n> {descricao}")

    if porta_ocupada(args.host, args.api_port):
        sys.exit(f"A porta {args.api_port} já está em uso. Use --api-port <outra porta>.")
    if porta_ocupada("127.0.0.1", args.front_port):
        sys.exit(f"A porta {args.front_port} (frontend) já está em uso. Use --front-port <outra porta>.")
    front_url = f"http://localhost:{args.front_port}/"
    abrir_url = front_url + ("#/simulador" if origem == "synthetic" else "")
    npm = shutil.which("npm")
    if npm is None:
        sys.exit("npm não encontrado no PATH. Instale o Node.js.")
    offline = modo == "local" and origem == "synthetic"
    preparar_frontend(npm, offline)
    if offline:
        sys.path.insert(0, str(ROOT))
        from tools.lab_launcher.config import carregar
        from tools.lab_launcher.docker_env import verificar_imagens_locais

        arquivo, valores = carregar(modo, Path(args.env_file) if args.env_file else None, False)
        try:
            verificar_imagens_locais(arquivo, dict(os.environ) | valores | {"RFID_LAB_OFFLINE": "1"})
        except (ValueError, RuntimeError, OSError) as erro:
            sys.exit(str(erro))
        print("Teste 1 offline: todos os serviços e arquivos são locais.", flush=True)

    ambiente = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8",
                    RFID_API_URL=f"http://{args.host}:{args.api_port}")
    if offline:
        ambiente.update(npm_config_offline="true", npm_config_update_notifier="false")
    # Com o launcher na frente, API e frontend escrevem em arquivo para não poluir o menu.
    com_launcher = origem is not None
    LOGS.mkdir(parents=True, exist_ok=True)
    log_api = LOGS / "api.log" if com_launcher else None
    log_front = LOGS / "front.log" if com_launcher else None

    api_cmd = [python, str(Path(__file__).resolve()), "--servir-api", modo,
               "--host", args.host, "--api-port", str(args.api_port)]
    if args.env_file:
        api_cmd += ["--env-file", args.env_file]
    if origem == "synthetic":
        api_cmd.append("--com-simulador")
    processos: list[subprocess.Popen] = []
    launcher: subprocess.Popen | None = None
    try:
        api = iniciar(api_cmd, ROOT, ambiente, log_api)
        front = iniciar([npm, "run", "dev", "--", "--port", str(args.front_port), "--strictPort"], FRONTEND, ambiente, log_front)
        processos += [api, front]
        print("Subindo API e frontend...", flush=True)
        for nome, url, processo, log in (("API", f"http://{args.host}:{args.api_port}/health", api, log_api),
                                         ("Frontend", front_url, front, log_front)):
            if not aguardar_http(url, processo):
                print(f"{nome} não respondeu em {url}.\n{ultimas_linhas(log)}", flush=True)
                return 1
        print(f"API: http://{args.host}:{args.api_port}/docs")
        print(f"Frontend: {front_url}")
        if origem == "synthetic":
            print(f"Simulador web: {abrir_url}")
        if log_api:
            print(f"Logs da API e do frontend: {LOGS}")
        if not args.sem_navegador:
            webbrowser.open(abrir_url)

        if not com_launcher:
            print("Ctrl+C encerra tudo.", flush=True)
            while all(processo.poll() is None for processo in processos):
                time.sleep(0.5)
            return 1

        print("\nAbrindo o launcher de laboratório...\n", flush=True)
        comando = [python, "-m", "tools.lab_launcher", "start", "--env", modo, "--source", origem]
        if args.mqtt_transport:
            comando += ["--mqtt-transport", args.mqtt_transport]
        if args.reaproveitar:
            comando.append("--reuse")
        if args.env_file:
            comando += ["--env-file", args.env_file]
        launcher = subprocess.Popen(comando, cwd=ROOT, env=dict(os.environ))
        return launcher.wait()
    except KeyboardInterrupt:
        # O launcher recebe o mesmo Ctrl+C e derruba os contêineres; esperar por ele.
        while launcher is not None and launcher.poll() is None:
            try:
                launcher.wait()
            except KeyboardInterrupt:
                pass
        return 0
    finally:
        print("Encerrando API e frontend...", flush=True)
        for processo in processos:
            encerrar(processo)


if __name__ == "__main__":
    sys.exit(main())
