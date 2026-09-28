"""
Concorrência da ISS-026 contra Postgres real, com threads e barreiras.

1. Falhas de login simultâneas: todas contadas (lock da linha do usuário) e
   o bloqueio dispara exatamente uma vez.
2. Rebaixamento cruzado: A rebaixa B enquanto B rebaixa A. O protocolo
   (admins ativos em ordem de id, depois o alvo) faz exatamente um ser
   recusado, sem deadlock e sem deixar o sistema com zero administradores.
   Uma barreira DENTRO de `travar_admins_ativos` força as duas transações a
   chegarem juntas ao lock — se alguém inverter a ordem (alvo primeiro),
   as duas já estarão segurando o próprio alvo ali e o deadlock é garantido,
   não uma questão de sorte.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import timedelta

import pytest
from sqlalchemy.orm import Session
from suporte_auth import INICIO, SENHA, consultar, inserir_usuario

from api import service_auth, service_usuarios
from api.config_auth import ConfiguracaoAuth
from db.models import Usuario

CONFIG = ConfiguracaoAuth(
    sessao_duracao=timedelta(minutes=480), login_max_tentativas=5,
    login_bloqueio=timedelta(minutes=15), cookie_seguro=True,
)
REPETICOES = 5


def _em_threads(alvos, timeout=60):
    resultados: list = [None] * len(alvos)

    def rodar(indice, alvo):
        try:
            resultados[indice] = ("ok", alvo())
        except Exception as erro:  # noqa: BLE001 - o teste inspeciona o tipo
            resultados[indice] = ("erro", erro)

    threads = [threading.Thread(target=rodar, args=item) for item in enumerate(alvos)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout)
        assert not thread.is_alive(), "thread travada: possível deadlock sem detecção"
    return resultados


@pytest.mark.parametrize("repeticao", range(REPETICOES))
def test_falhas_simultaneas_sao_todas_contadas_e_bloqueiam(engine, truncate_all, caplog,
                                                           repeticao):
    caplog.set_level(logging.INFO, logger="api")
    usuario_id = inserir_usuario(engine, "alvo@hupaa.example")
    total = 8  # 5 contam e bloqueiam; as 3 seguintes encontram a conta bloqueada
    barreira = threading.Barrier(total)

    def tentar():
        with Session(bind=engine) as db:
            barreira.wait(10)
            service_auth.autenticar(db, "alvo@hupaa.example", "errada-123", INICIO, CONFIG)

    resultados = _em_threads([tentar] * total)

    assert all(tipo == "erro" and isinstance(erro, service_auth.LoginRecusado)
               for tipo, erro in resultados), resultados
    tentativas, bloqueado_ate = consultar(
        engine, "SELECT tentativas_falhas, bloqueado_ate FROM usuarios WHERE id=:id",
        id=usuario_id)[0]
    assert bloqueado_ate == INICIO + timedelta(minutes=15)
    assert tentativas == 0
    eventos = [json.loads(r.getMessage())["evento"] for r in caplog.records
               if r.name.startswith("api")]
    assert eventos.count("conta_bloqueada") == 1
    assert eventos.count("login_recusado") == total


@pytest.mark.parametrize("repeticao", range(REPETICOES))
def test_rebaixamento_cruzado_simultaneo_recusa_exatamente_um(engine, truncate_all, monkeypatch,
                                                               repeticao):
    admin_a = inserir_usuario(engine, "a@hupaa.example", perfil="administrador")
    admin_b = inserir_usuario(engine, "b@hupaa.example", perfil="administrador")
    barreira = threading.Barrier(2)
    original = service_usuarios.travar_admins_ativos

    def travar_juntos(db):
        barreira.wait(10)
        return original(db)

    monkeypatch.setattr(service_usuarios, "travar_admins_ativos", travar_juntos)

    def rebaixar(autor, alvo):
        def executar():
            with Session(bind=engine) as db:
                return service_usuarios.atualizar(db, autor, alvo, perfil="operacional").id
        return executar

    resultados = _em_threads([rebaixar(admin_a, admin_b), rebaixar(admin_b, admin_a)])

    sucessos = [valor for tipo, valor in resultados if tipo == "ok"]
    recusas = [valor for tipo, valor in resultados if tipo == "erro"]
    assert len(sucessos) == 1, resultados
    assert len(recusas) == 1, resultados
    assert isinstance(recusas[0], (service_usuarios.UltimoAdministrador,
                                   service_usuarios.AutorSemPermissao)), repr(recusas[0])
    admins = consultar(
        engine, "SELECT count(*) FROM usuarios u JOIN perfis p ON p.id = u.perfil_id "
        "WHERE p.nome = 'administrador' AND u.ativo")[0][0]
    assert admins == 1
    assert consultar(engine, "SELECT count(*) FROM auditorias")[0][0] == 1


def test_troca_de_senha_e_login_simultaneos_nao_perdem_falhas(engine, truncate_all):
    """Troca com senha errada e login errado ao mesmo tempo: as duas falhas contam."""
    usuario_id = inserir_usuario(engine, "alvo@hupaa.example")
    with Session(bind=engine) as db:
        _token, sessao = service_auth.autenticar(db, "alvo@hupaa.example", SENHA, INICIO, CONFIG)
        sessao_id = sessao.sessao_id
    barreira = threading.Barrier(4)

    def login_errado():
        with Session(bind=engine) as db:
            barreira.wait(10)
            service_auth.autenticar(db, "alvo@hupaa.example", "errada-123", INICIO, CONFIG)

    def troca_errada():
        with Session(bind=engine) as db:
            sessao = service_auth.SessaoAutenticada(sessao_id, INICIO, db.get(Usuario, usuario_id))
            barreira.wait(10)
            service_auth.trocar_senha(db, sessao, "errada-123", "nova-senha-123", INICIO, CONFIG)

    _em_threads([login_errado, login_errado, troca_errada, troca_errada])

    assert consultar(engine, "SELECT tentativas_falhas FROM usuarios WHERE id=:id",
                     id=usuario_id)[0][0] == 4
