"""Abre o simulador visual: ``python -m tools.lab_simulator``.

O launcher (opções 1 e 4) passa broker e banco pelo ambiente. Para uso avulso,
``--env-file`` carrega um perfil sem sobrescrever variáveis já exportadas.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from .modelo import Item


def cadastrar(itens: list[Item]) -> dict[str, str]:
    """Vincula cada item a um equipamento com o nome escolhido.

    Nome já usado antes reaproveita o equipamento e a tag existentes; só nomes
    novos usam o EPC sorteado.
    """
    from api.database import SessionLocal
    from tools.lab_launcher.seed import TIPO_SINTETICO, epcs_por_nome, semear_equipamentos

    with SessionLocal() as session:
        existentes = epcs_por_nome(session, [item.nome for item in itens], TIPO_SINTETICO)
        for item in itens:
            item.epc = existentes.get(item.nome.strip(), item.epc)
        return semear_equipamentos(session, [(item.epc, item.nome) for item in itens],
                                   TIPO_SINTETICO)


def destino(config: dict[str, str]) -> str:
    """Formata a identificação do destino MQTT exibida na janela sem credenciais."""
    tls = config.get("MQTT_TLS_ENABLED", "false").lower() == "true"
    return (f"{'mqtts' if tls else 'mqtt'}://{config.get('MQTT_HOST', '?')}:"
            f"{config.get('MQTT_PORT', '?')}")


def main() -> int:
    """Executa a entrada de linha de comando de tools.lab_simulator.__main__; devolve o código de saída quando aplicável."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reader-id", default="reader-01")
    parser.add_argument("--portal-id", default="portal-01")
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    if not os.environ.get("DATABASE_URL"):
        parser.error("DATABASE_URL ausente: o simulador cadastra os itens no banco")

    import flet as ft

    from tools.lab_launcher.synthetic import Publicador

    from .app import Envio, Simulador

    config = dict(os.environ)
    envio = Envio(Publicador(config, args.reader_id, portal_id=args.portal_id))
    envio.iniciar()

    def iniciar(page: ft.Page) -> None:
        """Constrói o simulador Flet na página fornecida pelo runtime desktop."""
        page.title = "Simulador RFID · Laboratório EASY"
        page.window.width = 1280
        page.window.height = 760
        Simulador(page, envio, cadastrar, destino(config)).montar()

    try:
        ft.run(iniciar)
    finally:
        envio.parar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
