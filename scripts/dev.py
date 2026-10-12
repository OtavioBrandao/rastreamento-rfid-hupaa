"""Sobe ingestor MQTT, API FastAPI e frontend Vite em um só terminal.

Uso (na raiz do repositório):

    python scripts/dev.py                      # usa .env.cloud
    python scripts/dev.py --env-file .env.local
    python scripts/dev.py --sem-ingestor       # só API + frontend

Ctrl+C encerra os três processos. A saída de cada um aparece com prefixo
colorido ([ingestor], [api], [front]). Nenhuma credencial é lida ou exibida
por este script: o arquivo de ambiente é carregado pelos próprios processos.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
WINDOWS = os.name == "nt"
CORES = {"ingestor": "\033[35m", "api": "\033[36m", "front": "\033[32m"}
RESET = "\033[0m"


def python_do_projeto() -> str:
    for candidato in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if candidato.exists():
            return str(candidato)
    return sys.executable


def comandos(args: argparse.Namespace, python: str) -> dict[str, tuple[list[str], Path]]:
    env_file = str(args.env_file)
    selecionados: dict[str, tuple[list[str], Path]] = {}
    if not args.sem_ingestor:
        # O ingestor lê só os.environ; load_dotenv roda no Python da .venv, que já tem python-dotenv.
        codigo = ("import runpy, sys; from dotenv import load_dotenv; "
                  "load_dotenv(sys.argv[1]); runpy.run_module('rfid_ingestion', run_name='__main__')")
        selecionados["ingestor"] = ([python, "-c", codigo, env_file], ROOT)
    if not args.sem_api:
        selecionados["api"] = ([python, "-m", "uvicorn", "api.main:app", "--host", args.host,
                                "--port", str(args.api_port), "--env-file", env_file], ROOT)
    if not args.sem_front:
        npm = shutil.which("npm")
        if npm is None:
            sys.exit("npm não encontrado no PATH. Instale o Node.js ou use --sem-front.")
        selecionados["front"] = ([npm, "run", "dev"], FRONTEND)
    return selecionados


def repassar_saida(nome: str, processo: subprocess.Popen[bytes], cor: bool) -> None:
    prefixo = f"{CORES[nome]}[{nome}]{RESET} " if cor else f"[{nome}] "
    assert processo.stdout is not None
    for linha in iter(processo.stdout.readline, b""):
        texto = linha.decode("utf-8", errors="replace").rstrip()
        print(f"{prefixo}{texto}", flush=True)


def porta_ocupada(host: str, porta: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, porta)) == 0


def encerrar(processo: subprocess.Popen[bytes]) -> None:
    if processo.poll() is not None:
        return
    if WINDOWS:
        # npm.cmd abre node como filho; /T derruba a árvore inteira.
        subprocess.run(["taskkill", "/PID", str(processo.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        try:
            os.killpg(processo.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            processo.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(processo.pid, signal.SIGKILL)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sobe ingestor, API e frontend juntos.")
    parser.add_argument("--env-file", type=Path, default=Path(".env.cloud"),
                        help="arquivo de ambiente usado pelo ingestor e pela API (padrão: .env.cloud)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, default=8010)
    parser.add_argument("--sem-ingestor", action="store_true", help="não sobe o ingestor MQTT")
    parser.add_argument("--sem-api", action="store_true", help="não sobe a API FastAPI")
    parser.add_argument("--sem-front", action="store_true", help="não sobe o frontend Vite")
    parser.add_argument("--sem-cor", action="store_true", help="desativa cores nos prefixos")
    args = parser.parse_args()

    if not args.env_file.is_absolute():
        args.env_file = ROOT / args.env_file
    if not (args.sem_ingestor and args.sem_api) and not args.env_file.exists():
        sys.exit(f"Arquivo de ambiente não encontrado: {args.env_file}. Copie o .example correspondente.")

    if not args.sem_api and porta_ocupada(args.host, args.api_port):
        sys.exit(f"A porta {args.api_port} já está em uso por outro processo. "
                 f"Use --api-port <outra porta> (o proxy do frontend acompanha).")

    for fluxo in (sys.stdout, sys.stderr):
        fluxo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    python = python_do_projeto()
    selecionados = comandos(args, python)
    if not selecionados:
        sys.exit("Nada para subir: todos os processos foram desativados.")
    if "front" in selecionados and not (FRONTEND / "node_modules").exists():
        print("[front] node_modules ausente; executando npm ci...", flush=True)
        subprocess.run([selecionados["front"][0][0], "ci"], cwd=FRONTEND, check=True)

    cor = not args.sem_cor and sys.stdout.isatty()
    if WINDOWS and cor:
        os.system("")  # habilita sequências ANSI no console do Windows
    ambiente = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8",
                    RFID_API_URL=f"http://{args.host}:{args.api_port}")
    ambiente.pop("FORCE_COLOR" if not cor else "NO_COLOR", None)
    ambiente.update({"FORCE_COLOR": "1"} if cor else {"NO_COLOR": "1"})
    extras = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS
              else {"start_new_session": True})

    processos: dict[str, subprocess.Popen[bytes]] = {}
    try:
        for nome, (comando, pasta) in selecionados.items():
            processos[nome] = subprocess.Popen(comando, cwd=pasta, env=ambiente, stdout=subprocess.PIPE,
                                               stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **extras)
            threading.Thread(target=repassar_saida, args=(nome, processos[nome], cor), daemon=True).start()
        if "front" in processos:
            print("Frontend: http://localhost:5173/", flush=True)
        if "api" in processos:
            print(f"API: http://{args.host}:{args.api_port}/docs", flush=True)
        print("Ctrl+C encerra tudo.", flush=True)
        avisados: set[str] = set()
        while len(avisados) < len(processos):
            for nome, processo in processos.items():
                if nome not in avisados and processo.poll() is not None:
                    avisados.add(nome)
                    print(f"[{nome}] encerrou com código {processo.returncode}", flush=True)
            time.sleep(0.5)
        return max(processo.returncode or 0 for processo in processos.values())
    except KeyboardInterrupt:
        print("\nEncerrando...", flush=True)
        return 0
    finally:
        for processo in processos.values():
            encerrar(processo)


if __name__ == "__main__":
    sys.exit(main())
