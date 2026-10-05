# RFID Hospital MVP

MVP experimental para rastreabilidade aproximada por zonas de equipamentos hospitalares móveis do Hospital Universitário Professor Alberto Antunes (**HUPAA/UFAL**) utilizando **RFID UHF passivo**. A localização do equipamento é inferida a partir de sua última passagem confirmada por uma zona de leitura, não por posicionamento contínuo.

> 📖 **Ponto Central de Documentação:** Para uma visão aprofundada da arquitetura, implementação dos subsistemas, decisões de engenharia e relatórios de validação para a banca examinadora, consulte o **[Guia Completo da Documentação (docs/README.md)](docs/README.md)**.

---

## 1. Estado Atual da Entrega (Status do MVP)

O projeto priorizou a solidez da infraestrutura, a confiabilidade da ingestão e a integridade do banco de dados antes da camada de inferência de negócios.

### ✅ O que está IMPLEMENTADO e testado:
- **Broker MQTT e Ingestão (ISS-001):** Suporte dual a HiveMQ Cloud (TLS 8883, autenticação e ACLs restritas) e Mosquitto local (1883) com o mesmo ingestor.
- **Ambiente de Desenvolvimento Local (ISS-003, ISS-004):** Docker Compose para PostgreSQL e Mosquitto locais com reset protegido; pipeline de CI no GitHub Actions com Lint, Testes e Migrations descartáveis.
- **Normalização e Contrato Canônico (ISS-005):** Adapters (`ez700`, `simulator`), geração determinística de `event_id` (`sha256:...`) e contrato canônico com timestamp UTC.
- **Persistência Idempotente e ACK Manual (ISS-006):** Inserção em `leituras_brutas` via `ON CONFLICT (event_id) DO NOTHING` e confirmação manual (`PUBACK`) estritamente após o commit.
- **Resiliência e Recuperação Automática (ISS-007):** Supervisor com backoff exponencial truncado, jitter de 20%, taxonomia estrita de falhas e retenção durável no broker MQTT durante quedas do banco.
- **Gestão de Equipamentos e Tags (ISS-008, ISS-009, ISS-010):** CRUDs FastAPI para Tipos de Equipamentos e Equipamentos; associação temporal de EPCs (`[inicio, fim)`) com constraint de unicidade parcial (`uq_tag_ativa`).
- **Hierarquia Hospitalar (ISS-011):** CRUDs FastAPI de Andares, Setores e Zonas com validação de ciclo de vida (*guards* de integridade) e consulta da árvore física completa.
- **Topologia de Hardware (ISS-012):** CRUDs FastAPI de Leitores, Antenas e Portais; índice único parcial de porta ativa (`uq_antena_ativa_por_porta_leitor`); desacoplamento entre leitor e portal.
- **Topologia Lógica de Portais (ISS-013):** Mapeamentos temporais de antenas para lados A/B, zonas e funções operacionais, preservando histórico de configuração.
- **Debounce Temporal (ISS-014):** Consolidação em memória por `(EPC, antena_id)` usando event time, tolerância configurável a reordenação e estatísticas de RSSI, sem remover leituras brutas.
- **Detecção de Passagem (ISS-015):** Correlação temporal de observações em lados opostos do mesmo portal, com evidências rastreáveis e `direcao=NULL`.
- **Inferência de Direção (ISS-016):** Interpretação da ordem temporal A→B/B→A com topologia histórica, zonas de origem/destino e estados `confirmed`, `ambiguous` e `unknown`. Tolerância temporal inicial configurável de 100 ms, ainda sem validação física.
- **Histórico de Movimentações (ISS-018):** Ledger append-only, resolução temporal EPC → equipamento, correção manual e consulta cronológica paginada.
- **Última Zona do Equipamento (ISS-017):** Passagem confirmada grava histórico e atualiza a projeção em uma transação; eventos atrasados não fazem a zona regredir e a reconciliação recupera falhas após o commit da direção.
- **Busca operacional (ISS-019):** `GET /api/ativos` filtra por nome/patrimônio, tipo, EPC, status e última zona com paginação; dashboard e mapas consultam esta API. Consulte [contrato e limites](docs/implementations/iss-019-busca-ativos.md).
- **Ativos por zona (ISS-020):** a consulta existente por `zona` lista a última localização conhecida; veja a [semântica e validação sintética](docs/implementations/iss-020-ativos-por-zona.md).
- **Última localização na interface (ISS-021):** tabela e detalhe exibem andar → setor → zona e horário no fuso `America/Maceio`; o detalhe consulta o histórico paginado. Veja o [contrato e a validação](docs/implementations/iss-021-ultima-localizacao-interface.md).
- **Usuários e autenticação (ISS-026):** login por e-mail com sessão opaca em cookie `HttpOnly`/`SameSite=Strict`, Argon2id, bloqueio por conta, senha temporária e administração em `/usuarios`; o primeiro admin nasce por `python -m api.criar_admin`. Veja o [contrato](docs/implementations/iss-026-usuarios-autenticacao.md) e o [ADR 0009](docs/decisions/0009-autenticacao-sessao-opaca-cookie.md).
- **Perfis e permissões (ISS-027):** toda rota de negócio exige sessão e permissão (operacional consulta, administrador faz tudo); o dashboard pede login e troca de senha temporária. Veja a [matriz e as rotas](docs/implementations/iss-027-perfis-rbac.md).

- **Mapa e portais (ISS-023):** vínculos validados por IDs, regiões configuráveis e alternativa textual. Veja [implementação e limites físicos](docs/implementations/iss-023-mapa-portais.md).
- **Passagens em vai e vem (hotfix):** passagens consecutivas sem exigir 3 s de silêncio, com refratário e rejeição de reflexão quando a antena de origem continua lendo a tag. Veja o [hotfix](docs/implementations/hotfix-passagem-vai-e-vem.md).
- **Leituras e presença (hotfix):** página Leituras com contagem por tag e antena, tabela de equipamentos detectados abaixo dos mapas e última leitura no dashboard, separada da zona confirmada. Veja o [hotfix](docs/implementations/hotfix-leituras-presenca.md).
- **Ensaio físico no launcher (hotfix):** opções 2 e 3 perguntam as tags e o nome de cada equipamento; o broker externo aceita `mqtt` sem TLS por opt-in de laboratório. Veja o [hotfix](docs/implementations/hotfix-lab-tags-fisicas-mqtt-sem-tls.md).
- **Ingestor em lotes para banco remoto (hotfix):** gravação em lote, threads separadas para rede, gravação e inferência, e relógio da inferência limitado à leitura pendente; com o banco externo, passagem, direção e zona voltam a funcionar. Veja o [hotfix](docs/implementations/hotfix-ingestor-lotes-banco-remoto.md).
- **Simulador visual do laboratório:** opções 1 e 4 do launcher abrem uma janela Flet com a planta EASY; os itens nomeados recebem EPCs aleatórios e, arrastados até uma antena, geram leituras sintéticas para o broker local ou externo. Substitui os roteiros sintéticos. Veja a [implementação](docs/implementations/simulador-visual-laboratorio.md).
- **Atualização automática (ISS-033):** dashboard, mapas, detalhes e histórico atualizados a cada 2 s; leituras EASY a cada 1 s; botão global de recuperação e rótulo “Em trânsito”. Veja [comportamento e validação](docs/implementations/iss-033-atualizacao-automatica.md).

### ⏳ Próximos Passos (Backlog Imediato):
- **Validação física:** Calibrar debounce, janela de passagem e tolerância de direção no HUPAA.

> [!NOTE]
> O aceite final com **leitores físicos Identix EZ700 e na rede Wi-Fi hospitalar** permanece como **PENDENTE DE VALIDAÇÃO FÍSICA**, aguardando infraestrutura de TI do HUPAA. Os testes atuais comprovam o pipeline lógico via simuladores e contêineres Docker.

---

## 2. Arquitetura Resumida

```mermaid
flowchart LR
    LEITOR["Leitor RFID / Simulador"] -->|MQTT QoS 1| BROKER["HiveMQ Cloud (TLS) / Mosquitto"]
    BROKER -->|Paho MQTT| INGESTOR["Ingestor Python"]
    INGESTOR --> JSONL["Auditoria JSONL (raw_events.jsonl)"]
    INGESTOR -->|Transação Atômica| POSTGRES[("PostgreSQL (leituras_brutas)")]
    POSTGRES -->|Commit OK| INGESTOR
    INGESTOR --> DEBOUNCE["Debounce (observação consolidada)"]
    DEBOUNCE --> PASSAGEM["Detecção de passagem (direcao=NULL)"]
    PASSAGEM --> POSTGRES
    POSTGRES --> DIRECAO["ISS-016: direção e zonas na passagem"]
    DIRECAO --> POSTGRES
    DIRECAO --> LOCALIZACAO["ISS-017: histórico + última zona"]
    LOCALIZACAO --> POSTGRES
    INGESTOR -->|Manual ACK| BROKER
    FASTAPI["FastAPI API REST<br/>(Equipamentos, Zonas, Hardware)"] --> POSTGRES
```

---

## 3. Execução Rápida Local (Ubuntu 24.04 / Docker)

Para subir o ambiente de desenvolvimento local completo (PostgreSQL 16, Mosquitto e Ingestor):

```bash
# 1. Configurar variáveis de ambiente para desenvolvimento local
cp .env.local.example .env.local

# 2. Iniciar contêineres locais (PostgreSQL e Mosquitto)
docker compose up -d

# 3. Carregar variáveis na sessão
set -a; source .env.local; set +a

# 4. Iniciar o ingestor (timestamps numéricos EZ700 usam a hora de recepção)
python -m rfid_ingestion

# Ou alternativamente via Make:
make local-up
make status-local
```

### Publicar eventos de teste com o simulador:
```bash
make simulator-local
tail -n 3 data/raw_events.jsonl
```

### Teste de laboratório assistido:

```bash
python -m pip install -r requirements-lab.txt
python -m tools.lab_launcher
```

O launcher limpa a tela, mostra o menu, prepara o cadastro e abre observação
MQTT, logs do ingestor e leituras no banco. Nas opções sintéticas (1 e 4), abre o
simulador visual: escolha quantos itens e seus nomes, e arraste cada item até as
antenas A e B para gerar leituras. O menu oferece leitor físico ou simulador, com
broker e banco locais ou externos. `requirements-lab.txt` inclui o Flet do
simulador; a imagem Docker continua usando somente `requirements.txt`. Veja
[instruções para Windows 11 e Ubuntu](docs/lab_test_launcher.md).

### Iniciar a API FastAPI:
```bash
# Primeira vez (ISS-026): criar o administrador inicial; a senha é pedida no terminal
set -a; source .env.cloud; set +a
python -m api.criar_admin --nome "Seu Nome" --email voce@hupaa.example

python -m uvicorn api.main:app --host 127.0.0.1 --port 8010 --env-file .env.cloud
# Acesse a documentação interativa em http://127.0.0.1:8010/docs
```

O comando acima mantém o fluxo com banco e broker externos já configurados em
`.env.cloud` (arquivo local, ignorado pelo Git). Para revisar uma branch em um
worktree sem copiar esse arquivo nem a `.venv`, execute o Python da instalação
existente a partir da pasta original e acrescente
`--app-dir <caminho-do-worktree>`; o `--env-file .env.cloud` continua apontando
para o arquivo da pasta original. O frontend deve ser iniciado no mesmo worktree
para servir o código correspondente ao backend.

### Subir tudo com um comando (API, frontend e teste de laboratório):

```bash
python scripts/dev.py
```

O script mostra o menu do launcher de laboratório (1 a 4), sobe a API na porta
8010 e o frontend em http://localhost:5173/ apontando para o banco do teste
escolhido e entrega o terminal ao launcher, que sobe o backend em Docker, abre os
três terminais (MQTT, Ingestor e Banco) e, nas opções 1 e 4, o simulador visual.
`--sem-teste` sobe só API e frontend no banco externo. `Ctrl+C` encerra tudo.
Funciona em Windows 11 e Ubuntu 24.04. As opções 1 e 4 exigem
`pip install -r requirements-lab.txt` (Flet).
Veja as opções em [mapa com abas e script de desenvolvimento](docs/implementations/mapa-abas-cluster-zonas.md).

### Iniciar o frontend operacional (ISS-032B):

```bash
cd frontend
npm ci
npm run dev
# Abra http://localhost:5173/
```

O Dashboard consulta `GET /api/ativos`, `/api/dashboard/resumo` e `/api/dashboard/atividade`; os mapas HUPAA/EASY consultam `GET /api/ativos`. A planta continua esquemática e não indica posição exata. No EASY, o pulso das antenas mostra cada leitura recebida; o fluxo completo fica na página Leituras. Veja a [integração da ISS-019](docs/implementations/iss-019-busca-ativos.md), os [roteiros e leituras ao vivo](docs/implementations/roteiros-laboratorio-mapa-ao-vivo.md), a [integração do painel](docs/implementations/iss-032-frontend-dashboard.md) e o [redesenho com mapas](docs/implementations/iss-032-redesign-mapas.md).

---

## 4. Comandos de Verificação e Testes

```bash
# Instalar dependências de desenvolvimento
python -m pip install -r requirements-dev.txt

# Executar linters
python -m ruff check --select E4,E7,E9,F,I .

# Executar testes unitários e de integração
python -m pytest -q

# Executar smoke tests de infraestrutura
bash tests/reader-connectivity/mqtt/smoke-test.sh
bash tests/infrastructure/compose-smoke-test.sh
bash tests/infrastructure/resilience-smoke-test.sh
```

---

## 5. Estrutura e Mapa da Documentação

A documentação detalhada foi reorganizada segundo a **[Issue #51](docs/implementations/iss-051-reorganizacao-documentacao.md)**:

- **[Ponto de Entrada da Documentação](docs/README.md)**
- **Arquitetura:**
  - [Visão Geral e Diagramas de Sequência](docs/architecture/system-overview.md)
  - [Modelo de Dados e Entidades](docs/architecture/data-model.md)
  - [Diagrama Entidade-Relacionamento](docs/architecture/er-diagrama.mermaid)
- **Implementações Técnicas:**
  - [ISS-001: Ingestão MQTT Local e HiveMQ](docs/implementations/iss-001-mqtt-ingestion.md)
  - [ISS-002b: Configuração Neon PostgreSQL](docs/implementations/iss-002b-neon-setup.md)
  - [ISS-002c: Migrations Alembic](docs/implementations/iss-002c-migrations.md)
  - [ISS-003: Ambiente Docker Compose](docs/implementations/iss-003-docker-compose.md)
  - [ISS-004: Pipeline de CI](docs/implementations/iss-004-ci.md)
  - [ISS-005: Normalização e Contrato Canônico](docs/implementations/iss-005-rfid-normalization.md)
  - [ISS-006: Persistência Idempotente e ACK Manual](docs/implementations/iss-006-raw-readings-persistence.md)
  - [ISS-007: Resiliência e Recuperação do Ingestor](docs/implementations/iss-007-ingestor-resilience.md)
  - [ISS-008/009/010: Gestão de Equipamentos e Tags](docs/implementations/iss-008-009-010-equipamentos-epc.md)
  - [ISS-011: Hierarquia de Localização Hospitalar](docs/implementations/iss-011-localizacao-hospitalar.md)
  - [ISS-012: Topologia de Hardware](docs/implementations/iss-012-topologia-hardware.md)
  - [ISS-013: Topologia Lógica de Portais](docs/implementations/iss-013-topologia-logica-portais.md)
  - [ISS-014: Debounce Temporal de Leituras](docs/implementations/iss-014-debounce-leituras.md)
  - [ISS-015: Detecção de Passagem](docs/implementations/iss-015-deteccao-passagem.md)
  - [ISS-016: Inferência de Direção](docs/implementations/iss-016-inferencia-direcao.md)
  - [ISS-018: Histórico de Movimentações](docs/implementations/iss-018-historico-movimentacoes.md)
  - [ISS-017: Última Localização](docs/implementations/iss-017-ultima-localizacao.md)
  - [ISS-019: Busca operacional de ativos](docs/implementations/iss-019-busca-ativos.md)
  - [ISS-020: Ativos por última zona conhecida](docs/implementations/iss-020-ativos-por-zona.md)
  - [ISS-021: Última localização e horário na interface](docs/implementations/iss-021-ultima-localizacao-interface.md)
  - [ISS-026: Usuários e autenticação](docs/implementations/iss-026-usuarios-autenticacao.md)
  - [ISS-027: Perfis e permissões](docs/implementations/iss-027-perfis-rbac.md)
- **Experimentos e Evidências:**
  - [Índice de Evidências e Matriz de Testes](docs/experiments/README.md)
  - [Evidências MQTT e Rede](docs/experiments/mqtt/)
  - [Evidências de Ingestão e Persistência](docs/experiments/ingestion/)
- **Decisões Arquiteturais:**
  - [Índice de ADRs](docs/decisions/README.md)

---

## 6. Materiais do Projeto

- [Google Drive — RFID Hospital MVP](https://drive.google.com/drive/folders/1AYqcT6jRI6UQNMan_DnyVXhEiNwMNgse?hl=pt-br)
