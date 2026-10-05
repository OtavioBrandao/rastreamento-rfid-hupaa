"""
Gera a tabela Markdown "rota -> permissão" da ISS-027 por introspecção da app.

    python -m tools.tabela_permissoes

A tabela de docs/implementations/iss-027-perfis-rbac.md sai daqui; regenere
sempre que um router ou a matriz mudar (não edite à mão).
"""

from collections.abc import Iterator

from fastapi.routing import APIRoute

from api.dependencias_auth import sessao_autenticada
from api.main import app
from api.permissoes import MATRIZ, METODOS_DE_CONSULTA

PUBLICAS = {("GET", "/health"), ("POST", "/auth/login"), ("POST", "/auth/logout")}


def _rotas(rotas, prefixo: str = "") -> Iterator[tuple[str, APIRoute]]:
    for rota in rotas:
        if isinstance(rota, APIRoute):
            yield prefixo + rota.path, rota
        elif hasattr(rota, "original_router"):
            yield from _rotas(rota.original_router.routes, prefixo + rota.include_context.prefix)


def _chamadas(dependant) -> Iterator:
    for sub in dependant.dependencies:
        yield sub.call
        yield from _chamadas(sub)


def exigencia(metodo: str, rota: APIRoute) -> str:
    chamadas = list(_chamadas(rota.dependant))
    for chamada in chamadas:
        if hasattr(chamada, "permissao_consulta"):
            return (chamada.permissao_consulta if metodo in METODOS_DE_CONSULTA
                    else chamada.permissao_alteracao).value
        if hasattr(chamada, "permissoes_exigidas"):
            return ", ".join(sorted(p.value for p in chamada.permissoes_exigidas))
    if sessao_autenticada in chamadas:
        return "qualquer sessão"
    return "SEM PERMISSÃO"


def main() -> None:
    linhas = sorted(
        (caminho, metodo, rota) for caminho, rota in _rotas(app.routes) for metodo in rota.methods
    )
    print("| Método | Rota | Exige | Operacional | Administrador |")
    print("|---|---|---|---|---|")
    for caminho, metodo, rota in linhas:
        if (metodo, caminho) in PUBLICAS:
            exige, oper, admin = "pública", "✓", "✓"
        else:
            exige = exigencia(metodo, rota)
            if exige == "qualquer sessão":
                oper = admin = "✓"
            else:
                oper = "✓" if exige in MATRIZ["operacional"] else "—"
                admin = "✓" if exige in MATRIZ["administrador"] else "—"
        print(f"| {metodo} | `{caminho}` | {exige} | {oper} | {admin} |")
    print(f"\n{len(linhas)} rotas.")


if __name__ == "__main__":
    main()
