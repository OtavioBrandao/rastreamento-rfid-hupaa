import sys

from .cli import app

if len(sys.argv) == 1:
    sys.argv.append("start")

app()
