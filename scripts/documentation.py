"""Verifica docstrings e gera referência HTML com o pydoc da biblioteca padrão.

Uso na raiz: ``python scripts/documentation.py --check`` ou ``--html``.
A verificação usa AST sem importar o produto. A geração importa módulos para
inspecionar suas assinaturas; não inicia servidores, publicadores nem migrations.
Instale requirements/lab.txt para documentar também os módulos Flet.
"""

from __future__ import annotations

import argparse
import ast
import html
import importlib
import os
import pydoc
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = (
    "api", "db", "rfid_ingestion", "rfid_inference", "rfid_location",
    "rfid_movement", "tools", "scripts",
)
OUTPUT = ROOT / "docs" / "reference" / "html"


def sources() -> list[Path]:
    """Lista fontes Python de produto e ferramentas, excluindo caches e testes."""
    return sorted(path for package in PACKAGES for path in (ROOT / package).rglob("*.py"))


def module_name(path: Path) -> str:
    """Converte caminho da fonte no nome importável, tratando __init__ como pacote."""
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def check(paths: list[Path]) -> int:
    """Exige docstring em módulos, classes e funções, inclusive métodos privados.

    Devolve 1 e aponta as linhas sem descrição; devolve 0 se todas estiverem
    documentadas. Assinaturas e anotações são preservadas no próprio código.
    """
    missing = []
    total = 0
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                total += 1
                if not ast.get_docstring(node):
                    missing.append(f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', 1)} "
                                   f"{getattr(node, 'name', '<módulo>')}")
    if missing:
        print("Docstrings ausentes:\n" + "\n".join(missing))
        return 1
    print(f"Docstrings: {total} definições documentadas em {len(paths)} fontes.")
    return 0


def generate(paths: list[Path]) -> int:
    """Gera uma página pydoc por módulo e índice navegável, falhando se algum import falhar.

    Inclui funções privadas na página complementar de implementação, pois o
    pydoc omite esses nomes da referência pública. Não lê perfis de laboratório.
    A saída é local e ignorada pelo Git para evitar versionar artefatos gerados.
    """
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    documenter = pydoc.HTMLDoc()
    links = []
    errors = []
    for path in paths:
        name = module_name(path)
        if path.resolve() == Path(__file__).resolve():
            module = sys.modules[__name__]
        else:
            try:
                module = importlib.import_module(name)
            except Exception as error:
                # Mensagens de dependências podem incluir configuração local.
                errors.append(f"{name}: {type(error).__name__}")
                continue
        page = documenter.page(name, documenter.document(module))
        (OUTPUT / f"{name}.html").write_text(page, encoding="utf-8")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        entries = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                signature = node.name
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    signature += "(" + ast.unparse(node.args) + ")"
                    if node.returns:
                        signature += " -> " + ast.unparse(node.returns)
                entries.append(f"<h2>{html.escape(signature)}</h2><p>Linha {node.lineno}</p>"
                               f"<pre>{html.escape(ast.get_docstring(node) or '')}</pre>")
        private_name = f"{name}.implementation.html"
        (OUTPUT / private_name).write_text(
            documenter.page(name, "<h1>Definições e lógica</h1>" + "\n".join(entries)),
            encoding="utf-8",
        )
        links.append(f'<li><a href="{name}.html">{name}</a> · '
                     f'<a href="{private_name}">todas as definições</a></li>')
    index = documenter.page("Rastreamento RFID HUPAA", "<h1>Referência Python</h1><ul>"
                            + "\n".join(links) + "</ul>")
    (OUTPUT / "index.html").write_text(index, encoding="utf-8")
    if errors:
        print("Falha ao importar módulos (instale requirements/lab.txt):\n" + "\n".join(errors))
        return 1
    print(f"Referência HTML: {OUTPUT / 'index.html'} ({len(links)} módulos).")
    return 0


def main() -> int:
    """Processa --check/--html; sem opção executa a verificação de docstrings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verifica cobertura de docstrings")
    parser.add_argument("--html", action="store_true", help="gera referência navegável com pydoc")
    args = parser.parse_args()
    paths = sources()
    result = check(paths + sorted((ROOT / "alembic").rglob("*.py")))
    if result or not args.html:
        return result
    # Impede fallback de dotenv da API/migrations para arquivos da pasta corrente.
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    return generate(paths)


if __name__ == "__main__":
    raise SystemExit(main())
