"""Abertura dos três observadores em Windows e Ubuntu."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .config import ROOT

_TMUX_SESSION: str | None = None


def _powershell(args: list[str]) -> str:
    return "& " + " ".join("'" + part.replace("'", "''") + "'" for part in args)


def abrir(arquivo: Path, perfil: str, servico: str, env: dict[str, str],
          marker: Path) -> list[subprocess.Popen]:
    env = dict(env, LAB_SESSION_MARKER=str(marker), LAB_COMPOSE_ENV_FILE=str(arquivo),
               LAB_COMPOSE_PROFILE=perfil, LAB_INGESTOR_SERVICE=servico)
    comandos = [
        ("MQTT", [sys.executable, "-m", "tools.lab_launcher.watch", "mqtt"]),
        ("Ingestor", [sys.executable, "-m", "tools.lab_launcher.watch", "logs"]),
        ("Banco", [sys.executable, "-m", "tools.lab_launcher.watch", "db"]),
    ]
    processos = []
    if os.name == "nt":
        wt = shutil.which("wt")
        for titulo, comando in comandos:
            pasta = "'" + str(ROOT).replace("'", "''") + "'"
            script = f"Set-Location -LiteralPath {pasta}; " + _powershell(comando)
            ps = ["powershell.exe", "-NoExit", "-Command", script]
            prefixo = [wt, "-w", "0", "new-tab", "--title", titulo] if wt else []
            processos.append(subprocess.Popen(prefixo + ps, cwd=ROOT, env=env))
        return processos

    gnome = shutil.which("gnome-terminal")
    konsole = shutil.which("konsole")
    xterm = shutil.which("xterm")
    generic = shutil.which("x-terminal-emulator")
    if gnome or konsole or xterm or generic:
        for titulo, comando in comandos:
            linha = f"cd {shlex.quote(str(ROOT))} && " + shlex.join(comando) + "; exec bash"
            if gnome:
                args = [gnome, "--tab", "--title", titulo, "--", "bash", "-lc", linha]
            elif konsole:
                args = [konsole, "--hold", "-e", "bash", "-lc", linha]
            elif xterm:
                args = [xterm, "-hold", "-T", titulo, "-e", "bash", "-lc", linha]
            else:
                args = [generic, "-e", "bash", "-lc", linha]
            processos.append(subprocess.Popen(args, cwd=ROOT, env=env))
        return processos

    tmux = shutil.which("tmux")
    if tmux:
        global _TMUX_SESSION
        nome = f"rfid-lab-{os.getpid()}"
        subprocess.run([tmux, "new-session", "-d", "-s", nome, "-n", "observacao",
                        shlex.join(comandos[0][1]) + "; exec bash"],
                       cwd=ROOT, env=env, check=True)
        for _, comando in comandos[1:]:
            subprocess.run([tmux, "split-window", "-t", nome,
                            shlex.join(comando) + "; exec bash"],
                           cwd=ROOT, env=env, check=True)
        subprocess.run([tmux, "select-layout", "-t", nome, "tiled"], check=True)
        _TMUX_SESSION = nome
        print(f"Observação em tmux: tmux attach -t {nome}")
        return processos
    raise RuntimeError("instale um terminal gráfico ou tmux para abrir os observadores")


def encerrar(processos: list[subprocess.Popen]) -> None:
    for processo in processos:
        if processo.poll() is None:
            processo.terminate()
    if _TMUX_SESSION is not None and os.name != "nt" and shutil.which("tmux"):
        tmux = shutil.which("tmux")
        if subprocess.run([tmux, "has-session", "-t", _TMUX_SESSION],
                          capture_output=True).returncode == 0:
            subprocess.run([tmux, "kill-session", "-t", _TMUX_SESSION], check=True)
