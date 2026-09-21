# Log de Implementação — ISS-007: Resiliência e Recuperação do Ingestor

Este documento registra a implementação, sincronização e validação final da **ISS-007** (Issue #9, Pull Request #44) no repositório `OtavioBrandao/rfid-hospital-mvp`.

---

## 1. Identificação da Issue e Pull Request

- **Issue:** #9 — `[ISS-007][E2] Implementar reconexão, backoff e recuperação do ingestor`
- **Pull Request:** #44 — `feat(iss-007): adicionar resiliencia e recuperacao ao ingestor`
- **Branch:** `feat/iss-007-reconexao-recuperacao`
- **Base:** `main` (retargeted de `feat/iss-006-persistencia-idempotente`)

---

## 2. O que é a Issue e sua Importância para o MVP

Em um ambiente hospitalar real (como o HUPAA/UFAL), oscilações transientes de infraestrutura — como reinicialização momentânea do broker MQTT, instabilidade momentânea na rede ou indisponibilidade temporária do banco de dados PostgreSQL — não podem paralisar o pipeline de captura RFID nem exigir intervenção manual de operadores para reiniciar contêineres.

Antes desta issue:
1. Uma falha de conexão inicial ou desconexão do broker encerrava o processo ou deixava o ingestor inoperante.
2. Uma indisponibilidade do banco de dados durante a ingestão encerrava o receptor ou causava perda de mensagens em memória.
3. Não havia distinção clara entre falhas temporárias (que devem ser retentadas com backoff) e falhas permanentes de configuração (credenciais inválidas, certificados incorretos, ACL negada), gerando loops agressivos de reconexão inútil.

Com a **ISS-007**:
- O ingestor adota um supervisor dedicado com reconexão automática e **backoff exponencial truncado com jitter** para indisponibilidades temporárias.
- Implementa-se uma **taxonomia robusta de falhas**, diferenciando falhas transitórias de erros permanentes de autenticação/autorização/protocolo/certificados (`fail fast`).
- O fluxo de recuperação do PostgreSQL garante entrega *at-least-once* segura: na queda do banco, o consumo MQTT é pausado sem envio de ACK; o supervisor realiza sondas periódicas (`SELECT 1`) com backoff; quando o banco retorna, o ingestor reconecta ao MQTT e reassina o tópico, permitindo que o broker reentregue a mensagem pendente, que é inserida de forma idempotente via `ON CONFLICT (event_id) DO NOTHING`.
- Nenhuma exceção bruta, senha ou credencial é emitida nos logs estruturados.

---

## 3. Dependência e Sincronização com o Final da ISS-006

O PR #44 foi inicialmente desenvolvido sobre o branch antigo da ISS-006 (`feat/iss-006-persistencia-idempotente`). Com o merge bem-sucedido do PR #43 (`feat(iss-006): persistencia idempotente e auditoria de leituras brutas`) na branch `main`, tornou-se necessário sincronizar a ISS-007 diretamente com a versão final da `main` e alterar o alvo do PR #44 para `main`.

### Conflitos resolvidos na sincronização:
Foram resolvidos 18 arquivos conflitantes entre a antiga branch e a `main` atual:
- **Workflows e Migrations:** `.github/workflows/ci.yml`, `.github/workflows/migrations.yml`, `alembic/versions/da436f7c75b3_alinha_leituras_ao_contrato_canonico_.py` mantiveram a autoridade da `main` (linearidade de migrations e aplicação de `alembic upgrade head` no CI).
- **Modelagem e Diagramas:** `docs/database/er-diagrama.mermaid`, `docs/database/migrations.md`, `docs/database/modelagem-dados.md` mantiveram a autoridade da ISS-012/ISS-006 sobre hardware (`Leitor.reader_id`, `Antena.ativo`).
- **Runtime do Banco:** Em `db/runtime.py`, preservou-se `pool_pre_ping=True` da ISS-007 integrado ao `create_app_engine`.
- **Repositório de Persistência:** Em `rfid_ingestion/repository.py`, preservou-se a cláusula de resolução topológica `Antena.ativo.is_(True)` da ISS-012/ISS-006 e integraram-se os métodos `_database_failure_category`, `check_available()` e o tipo `PersistenceError` com suporte a `FailureCategory`.
- **Cliente MQTT:** Em `rfid_ingestion/mqtt_client.py`, preservaram-se o logging estruturado de normalização/persistência da ISS-006 e todo o fluxo de supervisão, reconexão com backoff e recuperação de banco da ISS-007.
- **Fixtures e Testes:** `tests/conftest.py` e `tests/fixtures/topology.sql` foram alinhados com a `main`; `tests/test_repository.py` manteve testes de antenas ativas e testes de classificação de erros/`pool_pre_ping`.
- **Scripts de Teste:** `tests/reader-connectivity/mqtt/smoke-test.sh` preservou a execução de `alembic upgrade head` no banco efêmero.
- **Retargeting do PR #44:** O base branch foi alterado de `feat/iss-006-persistencia-idempotente` para `main` via `gh pr edit 44 --base main`.

---

## 4. Histórico de Commits Criados na Finalização

1. **`723618d` — `chore(iss-007): sync with final iss-006 implementation`**
   - Sincronização e resolução de conflitos com `origin/main` após merge do PR #43.
2. **`9903049` — `fix(iss-007): classify mqtt connection failures`**
   - Classificação refinada de falhas de conexão MQTT e CONNACK, diferenciando DNS, broker indisponível, rede inalcançável, timeout, erro de rede, autenticação, autorização, client ID, protocolo e falha de certificado TLS.
3. **`e71fa2e` — `test(iss-007): cover mqtt failure categories`**
   - 15 novos casos de teste em `tests/test_mqtt_recovery.py` cobrindo todas as categorias de falha, parametrização de códigos CONNACK e exceções de socket, verificação de parada do supervisor em falhas permanentes e validação de mascaramento de credenciais e exceções brutas.
4. **`docs(iss-007): document resilience and final validation`**
   - Atualização de `docs/infrastructure/iss-007-ingestor-resilience.md` com a taxonomia detalhada e criação deste log de implementação em `docs/evidence/iss007/implementation-log.md`.

---

## 5. Taxonomia de Falhas Implementada

A resiliência do ingestor classifica falhas em duas categorias primárias (`FailureCategory`):
- `PERMANENT_CONFIGURATION`: Encerra o supervisor imediatamente (`fail fast`) para intervenção humana.
- `TEMPORARY_MQTT` / `TEMPORARY_DATABASE`: Dispara retentativas automáticas com backoff exponencial truncado e jitter.

### Mapeamento de Falhas de Conexão MQTT (`classify_connection_exception`):
- `socket.gaierror` → `TEMPORARY_MQTT` (`dns_failure`)
- `ConnectionRefusedError` (`ECONNREFUSED`) → `TEMPORARY_MQTT` (`broker_unavailable`)
- `TimeoutError`, `socket.timeout` → `TEMPORARY_MQTT` (`network_timeout`)
- `OSError` com `ENETUNREACH`, `EHOSTUNREACH`, `ENETDOWN` (POSIX e Windows WSA) → `TEMPORARY_MQTT` (`network_unreachable`)
- Demais `OSError` de rede (`ECONNRESET`, `EPIPE`) → `TEMPORARY_MQTT` (`network_error`)
- `SSLCertVerificationError` → `PERMANENT_CONFIGURATION` (`tls_certificate_failure`)

### Mapeamento de Códigos CONNACK MQTT (`classify_connack_code`):
- Código 1 / 132 → `PERMANENT_CONFIGURATION` (`protocol_rejected`)
- Código 2 / 133 → `PERMANENT_CONFIGURATION` (`client_id_rejected`)
- Código 3 / 136 → `TEMPORARY_MQTT` (`broker_unavailable`)
- Código 4 / 134 → `PERMANENT_CONFIGURATION` (`authentication_failure`)
- Código 5 / 135 → `PERMANENT_CONFIGURATION` (`authorization_failure`)

---

## 6. Comportamento de Recuperação do Broker MQTT

- **Sessão Persistente:** O cliente utiliza MQTT 3.1.1 com Client ID estável e `clean_session=False`.
- **Reassinatura Idempotente:** Ao restabelecer a conexão (`_on_connect`), o ingestor sempre reassina o tópico configurado com QoS 1, garantindo restauração do filtro mesmo em caso de reinício ou perda de estado do broker.
- **Supervisor e Backoff:** Um supervisor em thread desacoplada gerencia as tentativas com backoff exponencial truncado (padrão inicial 1s, máximo 30s) e jitter de 20%. O backoff é resetado após reconexão e restauração da assinatura.
- **Shutdown Cancelável:** Eventos de parada (`SIGINT`, `SIGTERM`, `stop()`) cancelam imediatamente a espera de backoff.

---

## 7. Comportamento de Recuperação do PostgreSQL

- **Detecção de Queda:** Falhas operacionais do banco (`OperationalError`, `DisconnectionError`, erros de conexão) são capturadas como `PersistenceError(category=FailureCategory.TEMPORARY_DATABASE)`.
- **Pausa de Consumo sem ACK:** Ao capturar falha temporária do banco, o ingestor limpa o status `ready`, define `database_unavailable`, **não envia PUBACK** para a mensagem atual e desconecta o cliente MQTT para evitar acúmulo descontrolado de mensagens em memória.
- **Sonda Periódica:** O supervisor executa a sonda segura `SELECT 1` (`repository.check_available()`) aplicando backoff exponencial e jitter.
- **Pool Pre-Ping:** `db/runtime.py` configura `pool_pre_ping=True` no engine SQLAlchemy, descartando automaticamente conexões mortas no pool após a restauração do banco.
- **Reconexão e Redelivery:** Uma vez restabelecida a conectividade com o banco, `database_unavailable` é limpo, o ingestor reconecta ao broker MQTT e reassina o tópico. O broker reentrega a mensagem não confirmada.
- **Idempotência:** A reentrega é processada por `RawReadingRepository.persist()`, onde o `INSERT ... ON CONFLICT (event_id) DO NOTHING` identifica que o `event_id` canônico já foi inserido (ou o insere com sucesso), retornando `PersistenceResult("duplicate")` ou `PersistenceResult("inserted")`. Em ambos os casos definitivos, o PUBACK é finalmente emitido ao broker.

---

## 8. Testes e Validações Executados

### Validação Estática e Linter:
```bash
python -m ruff check --select E4,E7,E9,F,I .
# All checks passed!
git diff --check
# Clean, no whitespace or conflict marker errors
```

### Testes Focados de Resiliência e Recuperação:
```bash
pytest tests/test_resilience.py tests/test_mqtt_recovery.py tests/test_database_recovery.py -v
# 54 passed in 0.18s
```

### Testes de Persistência e Repositório:
```bash
pytest tests/test_repository.py tests/test_mqtt_persistence.py -v
# 43 passed, 3 skipped in 0.25s
```

### Suíte Completa de Testes Unitários e de Integração:
```bash
pytest -q
# 230 passed, 457 skipped, 2 warnings, 52 subtests passed in 2.23s
```

---

## 9. Limitações e Trabalho Futuro

- **Sem garantia de Exactly-Once no canal:** O protocolo MQTT com QoS 1 oferece entrega *at-least-once*. A garantia de unicidade lógica é assegurada no PostgreSQL pela constraint de unicidade de `event_id`. O log de auditoria JSONL é *append-only* e pode conter múltiplos envelopes para uma mesma leitura reentregue.
- **Validação Física do Hardware:** Testes foram executados com simuladores e contêineres Mosquitto/PostgreSQL. A validação física do leitor Identix EZ700 (payloads brutos, MQTTS na rede física do HUPAA, calibração de RSSI) permanece como etapa futura de homologação em campo.
- **Features de Negócio:** Debounce de leituras (ISS-014) e inferência de sentido/passagem (ISS-015) pertencem a issues posteriores e estão fora do escopo da ISS-007.

---

## 10. Próximo Passo (NEXT STEP)

O PR #44 está sincronizado com a `main`, possui histórico limpo de commits atômicos, cobertura de testes completa para todas as categorias de falha e documentação atualizada. O PR está pronto para revisão final e merge no branch `main`.
