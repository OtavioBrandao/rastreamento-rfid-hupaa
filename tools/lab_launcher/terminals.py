"""Abertura dos três observadores em Windows e Ubuntu."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .config import ROOT

_TMUX_SESSION: str | None = None


def _sistema() -> str:
    return os.name


def _aguardar_prontos(marker: Path, kinds: tuple[str, ...], timeout: float = 10) -> tuple[str, ...]:
    prazo = time.monotonic() + timeout
    while True:
        ausentes = tuple(kind for kind in kinds if not marker.with_name(
            f"{marker.stem}.{kind}.ready").exists())
        if not ausentes or time.monotonic() >= prazo:
            return ausentes
        time.sleep(0.2)


def _exigir_prontos(marker: Path) -> None:
    ausentes = _aguardar_prontos(marker, ("mqtt", "logs", "db"))
    if ausentes:
        raise RuntimeError("observadores não iniciaram: " + ", ".join(ausentes)
                           + "; consulte as abas ou janelas abertas")


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
    if _sistema() == "nt":
        terminal = shutil.which("cmd.exe")
        if terminal is None:
            raise RuntimeError("cmd.exe não encontrado para abrir os observadores no Windows")
        windows_terminal = shutil.which("wt.exe") or shutil.which("wt")
        script = Path(__file__).with_name("watch_windows.cmd")
        if not script.is_file():
            raise RuntimeError("script dos observadores do Windows ausente")
        for titulo, comando in comandos:
            janela_env = dict(env, LAB_WATCH_KIND=comando[-1],
                              LAB_WATCH_PYTHON=sys.executable,
                              LAB_WATCH_TITLE=f"RFID {titulo}")
            if windows_terminal:
                args = [windows_terminal, "-w", "0", "new-tab", "--title", titulo,
                        "--suppressApplicationTitle", "--startingDirectory", str(ROOT),
                        "--inheritEnvironment", terminal, "/k", str(script)]
                print(f"Abrindo aba {titulo} no Windows Terminal...", flush=True)
                processos.append(subprocess.Popen(args, cwd=ROOT, env=janela_env))
            else:
                print(f"Abrindo janela {titulo} (Windows Terminal indisponível)...",
                      flush=True)
                processos.append(subprocess.Popen(
                    [terminal, "/k", str(script)], cwd=ROOT, env=janela_env,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                ))
        if windows_terminal:
            ausentes = _aguardar_prontos(marker, ("mqtt", "logs", "db"))
            for titulo, comando in comandos:
                if comando[-1] not in ausentes:
                    continue
                print(f"Aba {titulo} não iniciou; abrindo janela de recuperação...", flush=True)
                janela_env = dict(env, LAB_WATCH_KIND=comando[-1],
                                  LAB_WATCH_PYTHON=sys.executable,
                                  LAB_WATCH_TITLE=f"RFID {titulo}")
                processos.append(subprocess.Popen(
                    [terminal, "/k", str(script)], cwd=ROOT, env=janela_env,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                ))
        _exigir_prontos(marker)
        return processos

    interface_grafica = bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))
    gnome = shutil.which("gnome-terminal") if interface_grafica else None
    konsole = shutil.which("konsole") if interface_grafica else None
    xterm = shutil.which("xterm") if interface_grafica else None
    generic = shutil.which("x-terminal-emulator") if interface_grafica else None
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
        _exigir_prontos(marker)
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
        _exigir_prontos(marker)
        return processos
    raise RuntimeError("instale tmux ou execute com interface gráfica para abrir os observadores")


def encerrar(processos: list[subprocess.Popen]) -> None:
    if _sistema() == "nt":
        # O marcador encerra cada observador Python. Manter cmd aberto preserva
        # o histórico e evita deixar o filho órfão ao matar só o shell.
        return
    for processo in processos:
        if processo.poll() is None:
            processo.terminate()
    if _TMUX_SESSION is not None and _sistema() != "nt" and shutil.which("tmux"):
        tmux = shutil.which("tmux")
        if subprocess.run([tmux, "has-session", "-t", _TMUX_SESSION],
                          capture_output=True).returncode == 0:
            subprocess.run([tmux, "kill-session", "-t", _TMUX_SESSION], check=True)
