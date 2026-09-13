"""
Testes de db/url.py — em particular o cenário reportado na revisão de
código (Otávio): DATABASE_URL com senha percent-encoded (ex.: "%40"
para "@") fazia `alembic.config.Config.set_main_option` lançar
ValueError, porque o ConfigParser interno do Alembic trata "%" como
início de sintaxe de interpolação. A correção foi parar de passar a
URL por esse ConfigParser; estes testes garantem que get_database_url
nunca tenta interpolar nada — só repassa a string como está.
"""
import pytest

from db.url import get_database_url


def test_prioriza_database_url_do_ambiente(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://user:pass@host/db")
    assert (
        get_database_url(fallback="postgresql://fallback")
        == "postgresql+psycopg2://user:pass@host/db"
    )


def test_usa_fallback_quando_sem_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert get_database_url(fallback="postgresql://fallback") == "postgresql://fallback"


def test_url_com_percentual_nao_gera_valueerror(monkeypatch):
    """
    Reproduz o cenário do review: senha percent-encoded. Antes da
    correção, o equivalente desta chamada (via config.set_main_option)
    lançava ValueError e vazava a URL inteira, credencial junto, na
    mensagem de erro. get_database_url nunca deve tentar interpolar
    "%" — só retorna a string exatamente como veio.
    """
    url_com_percentual = "postgresql+psycopg2://review:example%40value@localhost/review"
    monkeypatch.setenv("DATABASE_URL", url_com_percentual)

    resultado = get_database_url(fallback="postgresql://fallback")

    assert resultado == url_com_percentual


def test_erro_claro_sem_database_url_nem_fallback(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        get_database_url(fallback=None)
