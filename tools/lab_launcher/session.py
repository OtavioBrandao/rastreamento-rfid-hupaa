"""Sinal local para encerrar observadores de uma execução anterior."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from .config import ROOT

SESSION_DIR = ROOT / ".lab_launcher"
STATE = SESSION_DIR / "session.json"


def _limpar_configs_orfas() -> None:
    """Remove arquivos temporários de observação sem sessão ativa correspondente."""
    if not SESSION_DIR.exists():
        return
    for path in SESSION_DIR.glob("*.watch.json"):
        token = path.name.removesuffix(".watch.json")
        if len(token) == 32 and all(c in "0123456789abcdef" for c in token):
            path.unlink(missing_ok=True)


def parar() -> None:
    """Remove o marcador de sessão e a configuração temporária dos observadores."""
    if not STATE.exists():
        _limpar_configs_orfas()
        return
    try:
        token = json.loads(STATE.read_text(encoding="utf-8"))["token"]
        if isinstance(token, str) and len(token) == 32 and all(c in "0123456789abcdef" for c in token):
            (SESSION_DIR / f"{token}.active").unlink(missing_ok=True)
            (SESSION_DIR / f"{token}.watch.json").unlink(missing_ok=True)
            for kind in ("mqtt", "logs", "db"):
                (SESSION_DIR / f"{token}.{kind}.ready").unlink(missing_ok=True)
    except (ValueError, KeyError, OSError):
        pass
    finally:
        STATE.unlink(missing_ok=True)
        _limpar_configs_orfas()


def iniciar() -> Path:
    """Cria marcador de sessão e arquivo temporário de ambiente ignorado pelo Git."""
    SESSION_DIR.mkdir(exist_ok=True)
    parar()
    token = uuid4().hex
    marker = SESSION_DIR / f"{token}.active"
    marker.touch()
    STATE.write_text(json.dumps({"token": token}), encoding="utf-8")
    return marker
