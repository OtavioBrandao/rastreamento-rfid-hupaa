"""Orquestração do Compose existente, limitada ao ambiente de laboratório."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import psutil

from .config import ROOT


@dataclass(frozen=True)
class HostBlocker:
    """Estrutura Host Blocker usada por tools.lab_launcher.docker_env.

    Campos: pid, name, ports, created."""
    pid: int | None
    name: str
    ports: tuple[int, ...]
    created: float | None


def _limpar_saida(saida: str, env: dict[str, str] | None) -> str:
    """Permite diagnosticar Docker sem exibir senhas ou URLs com credenciais."""
    if env:
        for chave, valor in env.items():
            if valor and ("PASSWORD" in chave.upper() or "TOKEN" in chave.upper()
                          or "SECRET" in chave.upper() or chave.upper().endswith("DATABASE_URL")):
                for segredo in (valor, quote(valor, safe="")):
                    if len(segredo) >= 4:
                        saida = saida.replace(segredo, "[oculto]")
    saida = re.sub(r"(\b[a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@",
                   r"\1[credenciais ocultas]@", saida, flags=re.IGNORECASE)
    saida = re.sub(r"(?i)\b(password|token|secret)\s*[=:]\s*[^\s,;]+",
                   r"\1=[oculto]", saida)
    return saida


def executar(args: list[str], *, env: dict[str, str] | None = None,
            mostrar: bool = False) -> str:
    """Executa comando Docker na raiz, captura progresso e oculta credenciais dos diagnósticos."""
    if mostrar:
        progresso = dict(os.environ if env is None else env)
        progresso.update(BUILDKIT_PROGRESS="plain", COMPOSE_PROGRESS="plain")
        processo = subprocess.Popen(args, cwd=ROOT, env=progresso, text=True,
                                    encoding="utf-8", errors="replace",
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        linhas = []
        assert processo.stdout is not None
        for linha in processo.stdout:
            limpa = _limpar_saida(linha.rstrip(), progresso)
            print(limpa, flush=True)
            linhas.append(limpa)
            linhas = linhas[-15:]
        codigo = processo.wait()
        if codigo:
            raise RuntimeError(f"comando terminou com código {codigo}:\n" + "\n".join(linhas))
        return "\n".join(linhas)
    result = subprocess.run(args, cwd=ROOT, env=env, text=True, encoding="utf-8",
                            errors="replace", capture_output=True)
    if result.returncode:
        detalhe = _limpar_saida((result.stderr or result.stdout).strip(), env)
        raise RuntimeError(f"comando terminou com código {result.returncode}: {detalhe[-2500:]}")
    return result.stdout.strip()


def compose(arquivo: Path, perfil: str, *args: str, env: dict[str, str] | None = None,
            mostrar: bool = False) -> str:
    """Invoca deploy/compose.yaml com perfil e arquivo explícitos, preservando a raiz do projeto."""
    return executar(["docker", "compose", "-f", str(ROOT / "deploy" / "compose.yaml"), "--env-file", str(arquivo), "--profile", perfil,
                     *args], env=env, mostrar=mostrar)


def _diagnostico(arquivo: Path, perfil: str, servico: str,
                 env: dict[str, str] | None) -> str:
    """Obtém últimas linhas sanitizadas do serviço Compose que falhou."""
    try:
        logs = compose(arquivo, perfil, "logs", "--no-color", "--tail", "20", servico,
                       env=env)
        return _limpar_saida(logs, env)[-2500:] or "sem logs disponíveis"
    except (OSError, RuntimeError):
        return "logs indisponíveis"


def conflitos(portas: tuple[int, ...], projeto: str) -> list[tuple[str, str]]:
    """Lista contêineres de outros projetos que publicam as portas necessárias ao ensaio."""
    saida = executar(["docker", "ps", "--format", "{{json .}}"])
    achados = []
    for linha in saida.splitlines():
        container = json.loads(linha)
        if container.get("Names", "").startswith(projeto + "-"):
            continue
        publicados = container.get("Ports", "")
        if any(re.search(rf":{porta}->", publicados) for porta in portas):
            achados.append((container["ID"], container["Names"]))
    return achados


def portas_do_projeto(portas: tuple[int, ...], projeto: str) -> set[int]:
    """Portas já publicadas pelos contêineres do próprio teste, que serão reutilizados."""
    saida = executar(["docker", "ps", "--format", "{{json .}}"])
    ocupadas = set()
    for linha in saida.splitlines():
        container = json.loads(linha)
        if not container.get("Names", "").startswith(projeto + "-"):
            continue
        publicados = container.get("Ports", "")
        ocupadas.update(porta for porta in portas if re.search(rf":{porta}->", publicados))
    return ocupadas


def processos_nas_portas(portas: tuple[int, ...], ignorar: set[int] | None = None) -> list[HostBlocker]:
    """Lista listeners TCP no host; PID indisponível nunca é encerrado às cegas."""
    ignorar = ignorar or set()
    grupos: dict[int | None, set[int]] = {}
    for conn in psutil.net_connections(kind="tcp"):
        if conn.status != psutil.CONN_LISTEN or not conn.laddr:
            continue
        porta = conn.laddr.port
        if porta in portas and porta not in ignorar:
            grupos.setdefault(conn.pid, set()).add(porta)
    resultado = []
    for pid, encontrados in grupos.items():
        try:
            processo = psutil.Process(pid) if pid is not None else None
            nome = processo.name() if processo else "PID indisponível"
            criado = processo.create_time() if processo else None
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            nome, criado = "processo inacessível", None
        resultado.append(HostBlocker(pid, nome, tuple(sorted(encontrados)), criado))
    return resultado


def encerrar_processos(bloqueios: list[HostBlocker]) -> None:
    """Encerra só os PIDs confirmados, sem tocar no daemon Docker."""
    for bloqueio in bloqueios:
        if bloqueio.pid is None or bloqueio.created is None:
            raise RuntimeError("porta ocupada por processo sem PID acessível")
        if bloqueio.pid in {0, 4, os.getpid(), os.getppid()}:
            raise RuntimeError("porta ocupada por processo do sistema ou do próprio launcher")
        if "docker" in bloqueio.name.lower() or "containerd" in bloqueio.name.lower():
            raise RuntimeError("porta ocupada pelo serviço Docker; verifique contêineres manualmente")
        try:
            processo = psutil.Process(bloqueio.pid)
            if processo.create_time() != bloqueio.created:
                raise RuntimeError("processo mudou antes do encerramento; verifique a porta novamente")
            processo.terminate()
            try:
                processo.wait(timeout=5)
            except psutil.TimeoutExpired:
                processo.kill()
                processo.wait(timeout=5)
        except psutil.TimeoutExpired as erro:
            raise RuntimeError("processo não encerrou após o tempo limite") from erro
        except (psutil.NoSuchProcess, psutil.AccessDenied) as erro:
            raise RuntimeError("sem permissão para encerrar processo que ocupa a porta") from erro


def porta_disponivel(endereco: str, porta: int) -> bool:
    """Testa bind TCP no endereço e porta sem iniciar listener permanente."""
    familia = socket.AF_INET6 if ":" in endereco else socket.AF_INET
    with socket.socket(familia, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((endereco, porta))
        except OSError:
            return False
    return True


def aguardar(arquivo: Path, perfil: str, servico: str, *, completo: bool = False,
            timeout: int = 120, env: dict[str, str] | None = None) -> None:
    """Aguarda healthcheck ou conclusão do serviço com timeout e diagnóstico sanitizado."""
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        ids = compose(arquivo, perfil, "ps", "-a", "-q", servico, env=env).splitlines()
        if ids:
            status = executar(["docker", "inspect", "--format",
                              "{{json .State}}", ids[0]], env=env)
            estado = json.loads(status)
            if completo:
                if estado.get("Status") == "exited":
                    if estado.get("ExitCode") == 0:
                        return
                    raise RuntimeError(f"{servico} terminou com código "
                                       f"{estado.get('ExitCode')}:\n"
                                       f"{_diagnostico(arquivo, perfil, servico, env)}")
            elif estado.get("Health", {}).get("Status") == "healthy":
                return
            elif estado.get("Status") == "running" and "Health" not in estado:
                return
            elif estado.get("Status") == "exited":
                raise RuntimeError(f"{servico} encerrou com código "
                                   f"{estado.get('ExitCode')}:\n"
                                   f"{_diagnostico(arquivo, perfil, servico, env)}")
        time.sleep(2)
    raise TimeoutError(f"tempo esgotado aguardando {servico}:\n"
                       f"{_diagnostico(arquivo, perfil, servico, env)}")
