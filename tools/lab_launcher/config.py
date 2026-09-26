"""Configuração do launcher sem expor segredos na linha de comando."""

from __future__ import annotations

import os
from pathlib import Path

import typer
from dotenv import dotenv_values, set_key
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[2]


def carregar(modo: str, arquivo: Path | None, interativo: bool) -> tuple[Path, dict[str, str]]:
    path = arquivo or ROOT / (".env.local" if modo == "local" else ".env.cloud")
    exemplo = path.with_name(path.name + ".example")
    if not path.exists() and exemplo.exists() and modo == "local":
        path.write_bytes(exemplo.read_bytes())
    valores = {k: v for k, v in dotenv_values(path).items() if v is not None}
    if modo == "managed":
        valores.update({k: v for k, v in os.environ.items() if k in {
            "MQTT_HOST", "MQTT_PORT", "MQTT_USERNAME", "MQTT_PASSWORD", "MQTT_CLIENT_ID",
            "MQTT_TOPIC", "DATABASE_URL", "APP_DATABASE_URL", "COMPOSE_PROJECT_NAME",
        }})
    if modo == "managed":
        obrigatorios = ("MQTT_HOST", "MQTT_USERNAME", "MQTT_PASSWORD", "MQTT_CLIENT_ID",
                        "DATABASE_URL", "APP_DATABASE_URL")
        faltantes = [k for k in obrigatorios if not valores.get(k) or any(
            marker in valores[k] for marker in ("example", "endpoint-do-cluster", "host-pooler")
        )]
        if faltantes and not interativo:
            raise ValueError("configuração externa incompleta: " + ", ".join(faltantes))
        novos = {}
        for chave in faltantes:
            novos[chave] = typer.prompt(
                chave, hide_input=chave in {"MQTT_PASSWORD", "DATABASE_URL", "APP_DATABASE_URL"}
            )
        if novos and typer.confirm("Salvar no arquivo local ignorado pelo Git?", default=False):
            path.touch(exist_ok=True)
            for chave, valor in novos.items():
                set_key(str(path), chave, valor)
            if os.name != "nt":
                path.chmod(0o600)
        valores.update(novos)
        path.touch(exist_ok=True)
        if os.name != "nt":
            path.chmod(0o600)
    elif not path.exists():
        path.touch()
    if modo == "local":
        url = URL.create(
            "postgresql+psycopg2",
            username=valores.get("POSTGRES_USER", "rfid_dev"),
            password=valores.get("POSTGRES_PASSWORD", "rfid_dev_only"),
            host="localhost",
            port=int(valores.get("POSTGRES_PORT", "5432")),
            database=valores.get("POSTGRES_DB", "rfid_hospital_dev"),
        ).render_as_string(hide_password=False)
        valores["DATABASE_URL"] = url
        valores["APP_DATABASE_URL"] = url
        valores["MQTT_HOST"] = "localhost"
        valores["MQTT_PORT"] = valores.get("MQTT_LOCAL_PORT", "1883")
        valores["MQTT_MODE"] = "local"
        valores["MQTT_TLS_ENABLED"] = "false"
        valores["MQTT_USERNAME"] = ""
        valores["MQTT_PASSWORD"] = ""
    else:
        valores["MQTT_MODE"] = "cloud"
        valores["MQTT_TLS_ENABLED"] = "true"
    return path, valores
