# Log de Implementação — Integração ISS-006 com ISS-012

Este documento registra os checkpoints incrementais de implementação da integração da ISS-006 (PR #43) com o modelo de hardware e domínio da ISS-012 (PR #50), permitindo rastreabilidade e continuidade por qualquer agente ou desenvolvedor.

---

## Checkpoint 1: Integração do modelo de hardware ISS-012

- **Commit SHA:** `81280aa`
- **Mensagem:** `chore(iss-006): integrate iss-012 hardware model`
- **O que foi concluído:**
  - Merge do branch `origin/feat/iss-012-crud-leitores-antenas-portais` no branch de trabalho `feat/iss-006-persistencia-idempotente`, preservando o histórico git.
  - Resolução de conflitos adotando o modelo da ISS-012 como autoritativo para `Leitor`, `Antena`, `Portal`, `reader_id` (NOT NULL, UNIQUE), ciclo de vida do hardware (`ativo`), e índice único parcial `uq_antena_ativa_por_porta_leitor`.
  - Remoção da definição duplicada de `reader_id` (versão nullable da ISS-006) em `db/models.py`.
  - Harmonização de fixtures em `tests/conftest.py` preservando as fixtures isoladas da ISS-006 (`pg_empty_schema`, `migration_config`, `pg_engine`, `topology`) e as fixtures do CRUD da ISS-008..012 (`engine`, `db`, `truncate_all`).
  - Atualização dos diagramas e documentação de modelagem (`docs/database/er-diagrama.mermaid`, `docs/database/modelagem-dados.md`).
- **Arquivos significativamente alterados:**
  - `db/models.py`
  - `tests/conftest.py`
  - `.github/workflows/migrations.yml`
  - `docs/database/er-diagrama.mermaid`
  - `docs/database/modelagem-dados.md`
  - Novos arquivos da stack ISS-008..012 (`api/*`, migrations ISS-008..012, testes da API e serviços)
- **Testes executados e resultado:**
  - `pytest tests/test_parsing.py tests/test_normalization.py tests/test_config.py tests/test_database_url.py tests/test_schemas_hardware.py tests/test_epc.py`: 135 passed, 35 subtests passed.
  - `ruff check --select E4,E7,E9,F .`: passou sem erros.
  - `ruff check --select I .`: passou sem erros.
  - `git diff --check`: limpo.
- **Trabalho restante:**
  - Fases 2 a 6.
- **Problemas conhecidos ou decisões pendentes:**
  - O grafo do Alembic possuía duas heads (`da436f7c75b3` e `6b3e5f7a91c4`), a ser unificado na Fase 3.
  - A query de persistência ainda não filtrava `Antena.ativo`, a ser resolvido na Fase 4.

---

## Checkpoint 2: Alinhamento da migration de persistência com ISS-012

- **Commit SHA:** `4697677`
- **Mensagem:** `fix(iss-006): align persistence migration with iss-012`
- **O que foi concluído:**
  - Alinhamento da migration `da436f7c75b3` para ter `down_revision = "6b3e5f7a91c4"` (head da ISS-012), unificando a árvore do Alembic em exatamente 1 head (`da436f7c75b3`).
  - Remoção das operações duplicadas de criação e remoção de `leitores.reader_id` e de sua constraint em `da436f7c75b3`, uma vez que a propriedade estrutural pertence à migration `019782a38ff7` da ISS-012.
  - Atualização de `tests/test_migrations.py` para validar o comportamento de backfill de `reader_id` conforme a ISS-012.
  - Ajuste pontual em `tests/test_migration_iss012.py` para apontar explicitamente para `REVISAO_ISS012_AJUSTES` nos testes de roundtrip e abort da cadeia de hardware.
- **Arquivos significativamente alterados:**
  - `alembic/versions/da436f7c75b3_alinha_leituras_ao_contrato_canonico_.py`
  - `tests/test_migrations.py`
  - `tests/test_migration_iss012.py`
- **Testes executados e resultado:**
  - `alembic heads`: exatamente 1 head (`da436f7c75b3`).
  - `alembic history`: cadeia linear completa de `<base>` até `da436f7c75b3`.
  - `pytest tests/test_migrations.py -v`: 2 passed.
  - `pytest tests/test_migration_iss012.py -v`: 11 passed.
  - `ruff check`: All checks passed.
  - `git diff --check`: limpo.
- **Trabalho restante:**
  - Fases 4 a 6.

---

## Checkpoint 3: Resolução de antena ativa durante a ingestão

- **Commit SHA:** `20bd6f5`
- **Mensagem:** `fix(iss-006): resolve active antenna during ingestion`
- **O que foi concluído:**
  - Atualização da query de resolução topológica em `rfid_ingestion/repository.py` para incluir a cláusula `Antena.ativo.is_(True)` no `outerjoin`.
  - Com isso, a ingestão ignora antenas inativas históricas que compartilham a mesma porta física com a antena ativa substituta.
  - Adição de teste unitário focado `test_inactive_antenna_is_rejected_as_unknown` em `tests/test_repository.py`, comprovando que uma antena inativa sozinha em uma porta resulta em `rejected` com motivo `unknown_antenna`.
- **Arquivos significativamente alterados:**
  - `rfid_ingestion/repository.py`
  - `tests/test_repository.py`
- **Testes executados e resultado:**
  - `pytest tests/test_repository.py tests/test_mqtt_persistence.py -v`: 28 passed.
  - `ruff check`: All checks passed.
  - `git diff --check`: limpo.
- **Trabalho restante:**
  - Fases 5 e 6.

---

## Checkpoint 4: Teste de regressão para substituição de antena

- **Commit SHA:** `33ce195`
- **Mensagem:** `test(iss-006): cover antenna replacement topology`
- **O que foi concluído:**
  - Implementação do teste de regressão `test_antenna_replacement_topology_resolves_active_antenna` em `tests/test_repository.py` cobrindo o ciclo completo:
    1. leitor com `reader_id="reader-01"`;
    2. Antena A na porta 1;
    3. desativação lógica de Antena A;
    4. cadastro de Antena B ativa na mesma porta 1;
    5. retenção de Antena A como registro histórico;
    6. persistência de leitura canônica recebida para `reader_id="reader-01"` e porta 1;
    7. persistência bem-sucedida (`status == "inserted"`);
    8. vínculo da leitura bruta à Antena B;
    9. preservação de Antena A inativa;
    10. ausência de exceção `MultipleResultsFound`.
- **Arquivos significativamente alterados:**
  - `tests/test_repository.py`
- **Testes executados e resultado:**
  - `pytest tests/test_repository.py tests/test_mqtt_persistence.py -v`: 29 passed.
  - `ruff check`: All checks passed.
  - `git diff --check`: limpo.
- **Trabalho restante:**
  - Fases 5 (harness smoke test) e 6 (documentação).

---

## Checkpoint 5: Ajuste dos fixtures e migrations nos smoke tests

- **Commit SHA:** `8e431e2`
- **Mensagem:** `test(iss-006): update smoke test fixtures and migration for iss-012`
- **O que foi concluído:**
  - Atualização do arquivo `tests/fixtures/topology.sql` para preencher `nome_normalizado` em `andares`, `setores` e `zonas` (exigência introduzida na ISS-011).
  - Execução de `alembic upgrade head` no banco efêmero criado pelo script `tests/reader-connectivity/mqtt/smoke-test.sh` antes de invocar a suíte de testes.
- **Arquivos significativamente alterados:**
  - `tests/fixtures/topology.sql`
  - `tests/reader-connectivity/mqtt/smoke-test.sh`
- **Testes executados e resultado:**
  - `bash tests/reader-connectivity/mqtt/smoke-test.sh`: 618 passed, 0 skipped, 47 subtests passed, [PASSOU].
  - `bash tests/infrastructure/compose-smoke-test.sh`: [PASSOU] Postgres/Mosquitto saudáveis, migration no head, ingestor e MQTT→JSONL/PostgreSQL, reset local ok.
  - `ruff check`: All checks passed.
  - `git diff --check`: limpo.
- **Trabalho restante:**
  - Fase 6: Documentação formal da integração e evidências.

---

## Checkpoint 6: Documentação da integração e validação

- **Commit SHA:** `f5347d7`
- **Mensagem:** `docs(iss-006): document iss-012 integration and validation`
- **O que foi concluído:**
  - Atualização de `docs/database/raw-readings-persistence.md` documentando a autoridade da ISS-012 sobre o modelo de hardware, a semântica de `reader_id` (NOT NULL, UNIQUE), a resolução exclusiva de antenas ativas na ingestão (`Antena.ativo.is_(True)`), a preservação do histórico de hardware inativo, a reorganização do grafo do Alembic (`da436f7c75b3` sucedendo `6b3e5f7a91c4`), e a preservação da idempotência canônica via `event_id`.
  - Atualização de `docs/database/migrations.md` (Seção 5) com a linhagem atualizada de migrations e delimitação de responsabilidades.
  - Registro detalhado deste log de implementação em `docs/evidence/iss006/implementation-log.md`.
- **Arquivos significativamente alterados:**
  - `docs/database/raw-readings-persistence.md`
  - `docs/database/migrations.md`
  - `docs/evidence/iss006/implementation-log.md`
- **Testes executados e resultado:**
  - `alembic heads`: exatamente 1 head (`da436f7c75b3`).
  - `alembic history`: cadeia linear íntegra de 7 migrations.
  - `alembic check`: `No new upgrade operations detected` (drift zero).
  - `pytest -q`: 616 passed, 2 skipped, 47 subtests passed (ou 618 passed com broker MQTT ativo).
  - `smoke-test.sh`: [PASSOU].
  - `compose-smoke-test.sh`: [PASSOU].
  - `ruff check`: All checks passed.
  - `git diff --check`: limpo.
- **Trabalho restante:**
  - Nenhum. Todas as fases (0 a 6) foram concluídas com sucesso.
- **Problemas conhecidos ou decisões pendentes:**
  - Nenhuma pendência aberta. A branch `feat/iss-006-persistencia-idempotente` está completamente integrada com a ISS-012 e validada.

---

## Checkpoint 7: Resolução de falha no CI, endurecimento de fixtures e sincronização com main

- **Commit SHA:** `5db3198`
- **Mensagem:** `docs(iss-006): record final integration validation`
- **Causa raiz da falha no CI (Root cause):**
  - O job `tests` no GitHub Actions iniciava um serviço PostgreSQL efêmero (`POSTGRES_DB: ci_db`), porém nunca executava `python -m alembic upgrade head` antes de invocar o `pytest`. Com o banco vazio sem as tabelas criadas, os testes com fixtures de banco falhavam imediatamente no setup com erros como `relation "auditorias" does not exist`.
- **Esgotamento em cascata do pool de conexões (Cascading connection pool exhaustion):**
  - A fixture `db` em `tests/conftest.py` abria a conexão e iniciava a transação externa antes de executar instruções `DELETE` preparatórias. Quando o DELETE falhava devido à tabela inexistente, a execução era abortada antes do bloco `try/finally` que continha `conexao.close()`. O vazamento de conexões não fechadas no pool (`QueuePool` tamanho 5, overflow 10) rapidamente esgotava a capacidade do pool após algumas falhas de setup, gerando o erro secundário em cascata `QueuePool limit of size 5 overflow 10 reached` para todos os testes subsequentes.
- **Ajustes de CI (Missing alembic upgrade head):**
  - O arquivo `.github/workflows/ci.yml` foi atualizado para definir `DATABASE_URL` apontando para o banco de serviço descartável do CI (além de `TEST_DATABASE_URL`), e foi adicionado o passo `Aplicar migrations no banco de testes` executando `python -m alembic upgrade head` imediatamente antes da suíte de testes.
- **Endurecimento de fixtures (Fixture hardening):**
  - A fixture `db` em `tests/conftest.py` foi reestruturada para envolver tanto a limpeza inicial de DELETEs quanto a criação/utilização da sessão em um bloco `try/finally` imediato após abrir a conexão e a transação externa. O bloco `finally` garante que `transacao_externa.rollback()` (se ativa) e `conexao.close()` sejam sempre invocados, mesmo em falhas catastróficas de setup/schema, prevenindo vazamento de conexões no pool.
- **Sincronização com o modelo final de hardware (Sync with final ISS-012 model):**
  - A branch foi sincronizada com `origin/main` (trazendo o merge das issues ISS-008..011).
  - Preservou-se a autoridade do modelo de hardware da ISS-012 (`Leitor.reader_id` NOT NULL + UNIQUE, `Antena.ativo`, restrição de porta única apenas entre antenas ativas, e filtro `Antena.ativo.is_(True)` na resolução de topologia em `rfid_ingestion/repository.py`).
  - Alinhou-se o cabeçalho docstring da migration `da436f7c75b3` (`Revises: 6b3e5f7a91c4`) com seu identificador de `down_revision`.
- **Validação e resultados (Validation results):**
  - `python -m ruff check --select E4,E7,E9,F,I .`: All checks passed.
  - `python -m alembic heads`: exatamente 1 head (`da436f7c75b3`).
  - `python -m alembic history`: cadeia linear íntegra de `<base>` até `da436f7c75b3`.
  - `python -m alembic upgrade head` + `python -m alembic check`: `No new upgrade operations detected` (drift zero).
  - Testes focados (`tests/test_repository.py`, `tests/test_migrations.py`, `tests/test_mqtt_persistence.py`, `tests/test_migration_iss012.py`): 42 passed em 53.49s.
  - Suíte completa de testes (`python -m pytest -q`): 632 passed, 2 skipped, 2 warnings, 47 subtests passed em 133.55s.
  - Teste de fumaça de infraestrutura (`tests/infrastructure/compose-smoke-test.sh`): [PASSOU] validando o fluxo crítico completo MQTT -> JSONL -> PostgreSQL, descarte idempotente de duplicatas via `ON CONFLICT DO NOTHING`, rejeição e ausência de ACK em falhas de banco, e integridade do reset local.
- **Status do PR:**
  - O PR #43 foi completamente validado e mesclado na branch `main` com sucesso (commit `537035c`).
