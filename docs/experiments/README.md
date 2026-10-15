# Experimentos e Evidências de Validação — Rastreamento RFID HUPAA

Este diretório centraliza os registros empíricos, evidências de testes de integração, relatórios de execução e documentação de laboratório do **Rastreamento RFID HUPAA**.

---

## 1. Classificação Rigorosa dos Ambientes de Teste

Para garantir honestidade técnica e precisão metodológica na apresentação acadêmica, toda evidência deste projeto é categorizada em um dos seguintes níveis:

| Nível de Validação | Descrição | O que comprova | O que NÃO comprova |
|---|---|---|---|
| **1. Simulador Sintético** | Scripts Python locais (`rfid_ingestion.simulator`) emitindo payloads JSON pré-definidos | Corretude do parser, normalização canônica, hashing determinístico e geração de schema | Comportamento do firmware do leitor real ou variações de sinal RF |
| **2. Docker Local / Efêmero** | Contêineres Linux de Mosquitto (1883) e PostgreSQL 16 executados em loopback | Idempotência de banco, concorrência, roundtrip de migrations e reconexão básica | Latência de WAN, certificados TLS públicos ou instabilidades de rede externa |
| **3. HiveMQ Cloud (Gerenciado)** | Cluster Serverless na nuvem com TLS (8883), TLS + autenticação por usuário/senha e ACLs por tópico | Resiliência com transporte criptografado e isolamento de permissões com simuladores (validado em 05/09/2026) | Conexão de leitores físicos no Wi-Fi hospitalar |
| **4. Hardware Físico em Bancada** | Leitores Identix EZ700 conectados via cabo de rede Ethernet ao notebook | Conectividade básica IP, DHCP e emissão de mensagens brutas pelo hardware | Funcionamento na rede Wi-Fi corporativa do hospital ou MQTTS em nuvem |
| **5. Rede Hospitalar (Campo)** | Operação nas dependências do HUPAA/UFAL sob infraestrutura da TI institucional | Aceite final de produção e viabilidade assistencial | *Status atual: PENDENTE DE VALIDAÇÃO FÍSICA* |

> [!IMPORTANT]
> **Testes com simuladores não constituem validação de hardware físico.**
> Embora a suíte automatizada execute centenas de testes unitários e de integração com verificação dos contratos cobertos pelos casos existentes, a homologação final do firmware Identix EZ700 no HiveMQ Cloud sob a rede do HUPAA permanece explicitamente documentada como **PENDENTE DE VALIDAÇÃO FÍSICA**.

---

## 2. Matriz de Evidências Disponíveis

- [Validação da candidata para o Marco 2](../operations/validation.md): testes
  automatizados, build, documentação e limites de reprodução em 15/10/2026.
- [Ensaio sintético local da candidata](ingestion/marco2-candidata-2026-10-15.json):
  publicador do simulador → Compose reorganizado → 12 leituras → passagem A→B
  confirmada → histórico e Zona B. Sem validação RF ou novo ensaio com leitor.

### 📡 Experimentos de Mensageria e Rede (`docs/experiments/mqtt/`)

- [Validação Local e Aceite da ISS-001](mqtt/iss001-evidence-local.md):
  - **Ambiente:** Mosquitto 2.1.2 em Docker local + scripts de verificação.
  - **Resultado:** 20/20 mensagens entregues por dois simuladores simultâneos; [relatório sanitizado em JSON](mqtt/local-2026-09-05.json).
- [Roteiro de Validação em Redes Distintas (ISS-001)](mqtt/iss001-managed-validation.md):
  - **Ambiente:** Procedimento para teste entre duas redes distintas (ex.: 4G móvel e rede cabeada) consumindo cluster HiveMQ Cloud provisionado (validado com simuladores em 05/09/2026; validação física presencial pendente).
- [Experimento Histórico em Redes Locais](mqtt/mqtt-network-validation.md):
  - **Ambiente:** Experimento inicial com hotspot e Wi-Fi local para diagnóstico de isolamento de clientes.
- [Relatório Histórico de Bancada — Identix EZ700 (PDF)](mqtt/test1_readers_communication.pdf):
  - **Ambiente:** Validação física anterior de comunicação MQTT em rede cabeada com dois leitores Identix EZ700 (`EZ700-82-8A-54` e `EZ700-82-89-14`).
  - **Nota:** Documento histórico que comprova viabilidade do leitor físico em rede local, mas anterior ao contrato canônico da ISS-005 e ao HiveMQ Cloud.

---

### ⚙️ Evidências de Ingestão, Persistência e Resiliência (`docs/experiments/ingestion/`)

- [Relatório de Entrega da Normalização (ISS-005)](ingestion/iss005-evidence.md):
  - **Ambiente:** Suíte de 46 testes com adapters `ez700` e `simulator`, normalização UTC e hashing determinístico de `event_id`.
- [Log de Implementação da Persistência Idempotente (ISS-006)](ingestion/iss006-implementation-log.md):
  - **Ambiente:** PostgreSQL 16 em Docker Desktop, testes com 8 tentativas concorrentes do mesmo `event_id` (1 inserção confirmada, 7 duplicatas ignoradas com sucesso), migração linear e resolução de antena ativa.
- [Log de Implementação da Resiliência e Recuperação (ISS-007)](ingestion/iss007-implementation-log.md):
  - **Ambiente:** Simulação de interrupção de broker MQTT e queda do PostgreSQL com sondas `SELECT 1`, reconexão com backoff e testes cobrindo todas as categorias de falhas de conexão.
- [Evidência de Validação da Topologia Lógica (ISS-013)](ingestion/iss013-validation.md):
  - **Ambiente:** Docker Local / PostgreSQL 16 e simulador sintético; suíte de testes cobrindo as 10 regras de topologia de portais, imutabilidade temporal `[inicio, fim)`, índice único parcial por antena ativa, guards de integridade cruzada e endpoints REST consolidados (validação física de bancada no HUPAA segue pendente de hardware).
- [Revisão da Sprint 2 após ensaio sintético gerenciado](ingestion/sprint2-revisao-sintetica-2026-09-26.md):
  - **Ambiente:** HiveMQ Cloud, ingestor e Neon; 100 mensagens sintéticas no formato observado do leitor, passagem A→B, movimentação e última zona confirmadas. Registra os testes e a calibração física ainda pendentes e os limites para avançar na Sprint 3.

---

## 3. Procedimento de Reprodução dos Testes Locais

Para reproduzir localmente as verificações automatizadas de ponta a ponta:

```bash
# 1. Ativar ambiente virtual e instalar dependências
source .venv/bin/activate
python -m pip install -r requirements/dev.txt

# 2. Executar linters de qualidade
python -m ruff check --config config/ruff.toml --select E4,E7,E9,F .
python -m ruff check --config config/ruff.toml --select I .

# 3. Executar suíte de testes unitários e de integração
# (PostgreSQL e Mosquitto locais devem estar em execução para testes integrados)
python -m pytest -q

# 4. Executar smoke test de conectividade MQTT
bash tests/reader-connectivity/mqtt/smoke-test.sh

# 5. Executar smoke test de resiliência e recuperação
bash tests/infrastructure/resilience-smoke-test.sh
```
