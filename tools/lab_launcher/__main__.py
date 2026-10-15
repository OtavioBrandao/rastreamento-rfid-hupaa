"""Componentes de tools.lab_launcher.__main__ do Rastreamento RFID HUPAA."""

import sys

from .cli import app


def main() -> None:
    """Abre o menu padrão ou executa o subcomando explícito da CLI de laboratório.

    Importar este módulo para pydoc não inicia Docker nem solicita entradas.
    """
    if len(sys.argv) == 1:
        sys.argv.append("start")
    app()


if __name__ == "__main__":
    main()
