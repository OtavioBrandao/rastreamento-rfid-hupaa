"""
Resolução da DATABASE_URL usada pelas migrations (alembic/env.py).

Isolado neste módulo, sem nenhum efeito colateral de import, para ser
testável em isolamento sem precisar simular o runtime do Alembic
(alembic/env.py executa código a nível de módulo que depende de um
MigrationContext ativo, o que o torna inviável de importar direto em
teste unitário).

Contrato importante (revisão de código, Otávio): o valor retornado aqui
NUNCA deve ser guardado de volta num `alembic.config.Config` via
`set_main_option`/`get_main_option`. Esses métodos passam pelo
`ConfigParser` interno do Alembic, que trata "%" como início de sintaxe
de interpolação — uma URL com senha percent-encoded (ex.: `%40` para
"@") faz `set_main_option` lançar `ValueError`, e essa exceção inclui a
URL completa (credencial junto) na mensagem, o que vaza a senha em log.
A URL retornada por esta função deve ir DIRETO para a criação do
Engine/contexto (`create_engine(url)` / `context.configure(url=url)`),
nunca através do ConfigParser.
"""
import os


def get_database_url(fallback: str | None = None) -> str:
    """
    Prioriza a variável de ambiente DATABASE_URL. Se ela não estiver
    definida, usa `fallback` (tipicamente o placeholder de alembic.ini).
    Levanta RuntimeError se nenhuma das duas estiver disponível.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    if fallback:
        return fallback
    raise RuntimeError(
        "Nenhuma DATABASE_URL definida (nem em DATABASE_URL no ambiente/.env, "
        "nem em sqlalchemy.url no alembic.ini)."
    )
