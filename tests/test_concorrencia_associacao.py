"""
Teste real de concorrência da ISS-010 — critério de aceitação "tentativa de
reutilizar EPC ativo é rejeitada inclusive sob concorrência".

Não usa a fixture `db` do conftest: ela embrulha tudo numa única conexão
com uma transação externa + SAVEPOINT (ver docstring de `db` em
`tests/conftest.py`), e duas savepoints da MESMA conexão não competem
entre si do jeito que duas transações reais em conexões reais competem —
um teste de corrida sobre ela não provaria nada sobre o comportamento em
produção. Aqui cada thread abre a PRÓPRIA conexão/sessão, via engines
independentes ligados à mesma `TEST_DATABASE_URL`.

Usa a fixture `truncate_all` para isolamento (limpeza real, commitada —
mesmo motivo de `tests/test_api_equipamento.py`: as sessões daqui não
enxergariam nada escrito dentro de uma transação externa não commitada).

O EPC usado nas duas threads é NOVO (nenhuma linha em `tags` para ele
antes do teste começar), de propósito: é o caso que força a corrida a
acontecer também dentro de `_obter_ou_criar_tag` (INSERT concorrente na
tabela `tags`, que tem seu próprio UNIQUE em `epc`, independente dos dois
índices parciais de associação) — não só na tabela de associações.
"""

from __future__ import annotations

import os
import threading

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.service_associacao import TagJaAssociada, associar, vinculo_ativo_por_equipamento
from api.service_equipamento import criar as criar_equipamento
from api.service_tipos_equipamento import criar as criar_tipo

EPC_DISPUTADO = "AABBCCDD"
TIMEOUT_SEGUNDOS = 15


def test_duas_threads_disputando_o_mesmo_epc_novo_apenas_uma_vence(truncate_all):
    url = os.environ["TEST_DATABASE_URL"]
    engine_a = create_engine(url, future=True)
    engine_b = create_engine(url, future=True)

    try:
        # Setup em sessão própria, commitada e fechada ANTES de disparar as
        # threads — para não segurar conexão/transação que interfira na
        # corrida real que o teste quer provocar.
        with Session(bind=engine_a, future=True) as setup:
            tipo = criar_tipo(setup, nome="Maca")
            equipamento_1 = criar_equipamento(
                setup,
                nome="Equipamento 1",
                tipo_id=tipo.id,
                identificador_interno="CONC-0001",
            )
            equipamento_2 = criar_equipamento(
                setup,
                nome="Equipamento 2",
                tipo_id=tipo.id,
                identificador_interno="CONC-0002",
            )
            equipamento_1_id = equipamento_1.id
            equipamento_2_id = equipamento_2.id

        barreira = threading.Barrier(2, timeout=TIMEOUT_SEGUNDOS)
        resultados: dict[str, tuple[str, object]] = {}
        trava_resultados = threading.Lock()

        def tentar_associar(nome_thread: str, engine, equipamento_id: int) -> None:
            session = Session(bind=engine, future=True)
            try:
                # Sincroniza as duas threads no ponto mais próximo possível
                # da tentativa real — maximiza a chance de as duas
                # executarem o SELECT inicial de `_obter_ou_criar_tag`
                # antes de qualquer uma commitar.
                barreira.wait()
                associacao = associar(session, equipamento_id, EPC_DISPUTADO)
                resultado = ("sucesso", associacao.equipamento_id)
            except TagJaAssociada as erro:
                resultado = ("falhou_tag_ja_associada", str(erro))
            except Exception as erro:  # pragma: no cover - só para diagnóstico de falha
                resultado = ("erro_inesperado", repr(erro))
            finally:
                session.close()
            with trava_resultados:
                resultados[nome_thread] = resultado

        thread_a = threading.Thread(
            target=tentar_associar, args=("A", engine_a, equipamento_1_id)
        )
        thread_b = threading.Thread(
            target=tentar_associar, args=("B", engine_b, equipamento_2_id)
        )
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=TIMEOUT_SEGUNDOS)
        thread_b.join(timeout=TIMEOUT_SEGUNDOS)

        assert not thread_a.is_alive(), "thread A não terminou a tempo (possível deadlock)"
        assert not thread_b.is_alive(), "thread B não terminou a tempo (possível deadlock)"
        assert set(resultados) == {"A", "B"}, resultados

        sucessos = [r for r in resultados.values() if r[0] == "sucesso"]
        falhas = [r for r in resultados.values() if r[0] == "falhou_tag_ja_associada"]

        # Nenhum "erro_inesperado": se aparecer aqui, é sinal de que a
        # corrida escapou pelo lugar que este teste existe para fechar
        # (ex.: IntegrityError cru em vez de TagJaAssociada).
        assert not [r for r in resultados.values() if r[0] == "erro_inesperado"], resultados
        assert len(sucessos) == 1, f"esperado exatamente 1 sucesso, veio {resultados}"
        assert len(falhas) == 1, f"esperado exatamente 1 falha, veio {resultados}"

        vencedor_equipamento_id = sucessos[0][1]
        perdedor_equipamento_id = (
            equipamento_2_id if vencedor_equipamento_id == equipamento_1_id else equipamento_1_id
        )

        with Session(bind=engine_a, future=True) as verificacao:
            vinculo_vencedor = vinculo_ativo_por_equipamento(verificacao, vencedor_equipamento_id)
            assert vinculo_vencedor is not None
            assert vinculo_vencedor.tag.epc == EPC_DISPUTADO

            # O perdedor não pode ter ficado com NENHUM vínculo ativo —
            # a corrida tem que resultar em exatamente um vencedor, nunca
            # em duplicidade nem em "os dois falharam".
            assert vinculo_ativo_por_equipamento(verificacao, perdedor_equipamento_id) is None
    finally:
        engine_a.dispose()
        engine_b.dispose()
