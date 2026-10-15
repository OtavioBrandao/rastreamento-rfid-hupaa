# Evidência de Validação — ISS-013: Topologia Lógica Versionada de Portais

Este documento registra a execução empírica e a comprovação automatizada dos contratos e regras de negócio da **ISS-013** (`[ISS-013][E3] Configurar lados, zonas e funções das antenas no portal`).

---

## 1. Contexto e Objetivo do Teste

A ISS-013 resolve a questão fundamental: *"O que cada antena significa dentro deste portal?"*. Ela conecta a infraestrutura física de RFID (`leitores` e `antenas`) à topologia hospitalar (`portais` delimitando `zona_a` e `zona_b`), permitindo aos futuros motores de inferência (ISS-015) determinar o sentido de deslocamento das tags.

O objetivo desta validação é comprovar:
1. **Regras de Integridade e Invariantes de Domínio (R1 a R10):** Rejeição estrita de inconsistências topológicas (antena inativa, portal inativo, zonas inconsistentes com o lado A/B, funções não operacionais, duplicidade de antenas em portais ativos).
2. **Preservação Histórica e Imutabilidade Temporal (`[inicio, fim)`):** Fechamento de vínculos antigos com `fim = now()` e criação de novos vínculos com `fim = NULL`, sem jamais executar `DELETE` ou `UPDATE` destrutivo sobre dados históricos.
3. **Migration Alembic e Backfill Seguro:** Criação da tabela `mapeamentos_antena_portal`, índice único parcial `uq_mapeamento_antena_ativo`, e migration com fail-fast caso existam dados legados incoerentes.
4. **Proteção Cruzada de Entidades de Hardware:** Bloqueio de exclusão ou inativação de portais e antenas que possuam mapeamentos ativos.
5. **Endpoints REST da API FastAPI:** Configuração atômica, associação unitária, desativação lógica, consulta consolidada de topologia e auditoria de histórico.

---

## 2. Classificação do Nível de Validação

Conforme a matriz metodológica descrita em [`docs/experiments/README.md`](../README.md#1-classificação-rigorosa-dos-ambientes-de-teste):

- **Nível 1 (Simulador Sintético / Mock):** Testes unitários com schemas Pydantic e mocks de isolamento de contratos.
- **Nível 2 (Docker Local / PostgreSQL Efêmero):** Testes de migração Alembic, constraints relacionais no PostgreSQL, concorrência e endpoints FastAPI sobre sessões SQLAlchemy.
- **Hardware Físico no HUPAA:** **PENDENTE DE VALIDAÇÃO FÍSICA.**
  > [!IMPORTANT]
  > Os testes desta entrega comprovam matematicamente e relacionalmente a lógica do software, as constraints no banco e a API REST. A validação física do arranjo de antenas com o leitor Identix EZ700 nos batentes do HUPAA depende da liberação de infraestrutura de TI do hospital.

---

## 3. Cenários de Teste Automatizados

### Cenário 1: Migração Alembic e Fail-Fast (`tests/test_migration_iss013.py`)
- **Objetivo:** Garantir a aplicação da revisão `68e5a26c2e17` (revisando `da436f7c75b3`), com criação de constraints e backfill controlado.
- **Verificações:**
  - Roundtrip upgrade (`base -> head`) e downgrade (`head -> da436f7c75b3`).
  - Criação da tabela `mapeamentos_antena_portal` e índice parcial `uq_mapeamento_antena_ativo`.
  - Backfill seguro: antenas pré-existentes válidas vinculadas a portais herdaram lado ('A' para zona_a, 'B' para zona_b) e função ('entrada'/'saida').
  - Fail-fast: tentativa de migrar com antena apontando para uma terceira zona desconhecida ou com função `'indefinido'` aborta a transação com mensagem de erro explícita sem corromper o banco.

### Cenário 2: Invariantes do Serviço de Domínio (`tests/test_service_topologia_portal.py`)
- **Objetivo:** Comprovar a aplicação das 10 regras de negócio pelo serviço de topologia.
- **Verificações:**
  - **R1:** Portal inexistente ou inativo rejeitado (`PortalNaoEncontrado` / `PortalInativo`).
  - **R2:** Zonas inválidas, inativas ou idênticas rejeitadas (`ZonaInvalidaParaPortal`).
  - **R3:** Antena inexistente ou inativa rejeitada (`AntenaNaoEncontrada` / `AntenaInativa`).
  - **R4:** Antena pertence ao leitor cadastrado, que deve estar ativo no cadastro (`LeitorInativo`).
  - **R5:** Lado rejeitado se diferente de `'a'` ou `'b'`.
  - **R6:** Tentativa de mapear lado 'a' com ID da zona B (ou vice-versa) rejeitada (`ZonaIncompativelComLado`).
  - **R7:** Função rejeitada se diferente de `'entrada'`, `'saida'` ou `'auxiliar'` (função `'indefinido'` rejeitada no portal).
  - **R8:** Antena com mapeamento ativo em outro portal bloqueada (`MapeamentoAtivoExistente` / `uq_mapeamento_antena_ativo`).
  - **R9:** Múltiplas antenas permitidas no mesmo lado e portal (ex.: duas antenas cobrindo lado A).
  - **R10:** Reconfiguração fecha mapeamento anterior com timestamp e abre novo registro ativo (`fim IS NULL`).
  - **Proteção:** Bloqueio de mutação ou inativação de portal (`PortalComMapeamentosAtivos`), antena (`AntenaComMapeamentoAtivo`) e leitor (`LeitorComMapeamentosAtivos`) com mapeamento ativo.

### Cenário 3: Endpoints REST FastAPI (`tests/test_api_topologia_portal.py`)
- **Objetivo:** Validar as rotas HTTP, validação de payload Pydantic e códigos de status.
- **Verificações:**
  - `POST /portais/{portal_id}/mapeamentos`: Criação de mapeamento lógico ativo (201 Created).
  - `GET /portais/{portal_id}/mapeamentos`: Listagem de mapeamentos do portal com suporte a `?incluir_historico=true` (200 OK).
  - `GET /portais/{portal_id}/topologia`: Consulta consolidada em join único para inferência (200 OK).
  - `GET /mapeamentos-antena/{mapeamento_id}`: Detalhamento de um mapeamento (200 OK).
  - `PATCH /mapeamentos-antena/{mapeamento_id}`: Atualização temporal com encerramento de versão anterior e abertura de nova (200 OK).
  - `POST /mapeamentos-antena/{mapeamento_id}/inativar`: Desativação lógica com timestamp `fim` (200 OK).
  - `GET /antenas/{antena_id}/mapeamentos`: Histórico cronológico de mapeamentos de uma antena (200 OK).
  - Erros 404 (não encontrado), 409 (conflito / guards de hardware) e 422 (incompatibilidade / entidade inativa) retornados com detalhamento padronizado.

---

## 4. Comandos Executados e Resultados Obtidos

### 4.1 Linters de Qualidade e Imports
```bash
python -m ruff check --config config/ruff.toml --select E4,E7,E9,F,I .
```
- **Esperado:** Zero erros ou warnings de sintaxe, imports ou formatação.
- **Obtido:** `All checks passed!`

### 4.2 Verificação de Migrations Alembic
```bash
python -m alembic heads
```
- **Esperado:** Exatamente uma única head linear: `68e5a26c2e17`.
- **Obtido:** `68e5a26c2e17 (head)`

### 4.3 Execução da Suíte de Testes
```bash
python -m pytest -q
```
- **Ambiente Local (sem PostgreSQL local ativo):** `230 passed, 485 skipped, 52 subtests passed` (485 skips de testes que requerem banco PostgreSQL local ativo via `TEST_DATABASE_URL`).
- **Ambiente de Integração Contínua (GitHub Actions CI — Run #35675783122):**
  - **Job Lint:** Aprovado em 14s (`All checks passed!`).
  - **Job Testes:** Aprovado em 1m50s (`715 passed, 2 warnings, 52 subtests passed`).
  - **Job Migrations / Validação completa:** Aprovado em 1m53s (`713 passed, 2 skipped, 2 warnings, 52 subtests passed`), com inspeção de schema confirmando exatamente 18 tabelas (17 do domínio + `alembic_version`).

---

## 5. Matriz de Resultados

| ID | Cenário / Requisito | Resultado Esperado | Resultado Obtido | Status |
|---|---|---|---|---|
| VAL-013-01 | Modelagem da tabela `mapeamentos_antena_portal` | Campos `portal_id`, `antena_id`, `zona_id`, `lado`, `funcao`, `inicio`, `fim` | Modelo SQLAlchemy e DDL criados conforme especificação | APROVADO |
| VAL-013-02 | Unicidade parcial por antena ativa | No máximo um registro ativo (`fim IS NULL`) por antena | Constraint `uq_mapeamento_antena_ativo` aplicada com sucesso | APROVADO |
| VAL-013-03 | Imutabilidade do histórico | Mapeamento antigo recebe `fim = now()`, novo registro criado | Teste temporal confirma existência do histórico e encerramento de vínculo | APROVADO |
| VAL-013-04 | Validação de Lado vs Zona (R6) | Rejeitar lado A com zona_b ou lado B com zona_a | Exceção de domínio tratada com HTTP 422 | APROVADO |
| VAL-013-05 | Validação de Funções Permitidas (R7) | Aceitar apenas `entrada`, `saida`, `auxiliar` | Rejeição de valores arbitrários ou `indefinido` com HTTP 422 | APROVADO |
| VAL-013-06 | Multi-antenas por lado (R9) | Permitir 2+ antenas no mesmo lado e portal | Suportado sem colisão de constraints | APROVADO |
| VAL-013-07 | Endpoint consolidado de topologia | Retornar portal, zonas A/B e antenas em query única | Endpoint `/portais/{id}/topologia` retorna DTO consolidado com dados de hardware e lógica | APROVADO |
| VAL-013-08 | Guard de integridade cruzada | Bloquear mutação/inativação de hardware com mapeamento ativo | Erros `PortalComMapeamentosAtivos`, `AntenaComMapeamentoAtivo` e `LeitorComMapeamentosAtivos` com HTTP 409 | APROVADO |
| VAL-013-09 | Validação física de bancada | Teste com leitores físicos Identix EZ700 | Aguardando infraestrutura de TI do HUPAA | PENDENTE DE HARDWARE |

---

## 6. Próximos Passos Habilitados pela ISS-013

Com a topologia lógica consolidada e versionada, o sistema dispõe dos metadados necessários para:
1. **ISS-014:** Debounce temporal de leituras por antena/portal.
2. **ISS-015:** Motor de inferência de passagens (comparação sequencial entre leituras de antenas do Lado A e Lado B com funções de entrada/saída).
3. **ISS-016:** Atualização da localização dos equipamentos com base no destino da passagem inferida.
