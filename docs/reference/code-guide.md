# Guia técnico do código

O backend usa Python 3.12. Os módulos, classes, funções e métodos de produto e
ferramentas têm docstrings em português. As assinaturas mantêm tipos, valores
padrão e argumentos nomeados. A documentação gerada é derivada dessas fontes.

## Consultar e gerar pydoc

```bash
python -m pip install -r requirements/lab.txt
python -m pydoc api.service_busca_ativos
python -m pydoc rfid_inference.passage
python scripts/documentation.py --check
python scripts/documentation.py --html
```

Abra `docs/reference/html/index.html` após gerar. Cada módulo tem referência
pydoc pública e uma página de **todas as definições**, incluindo métodos privados
e funções internas que o pydoc normalmente omite. O gerador usa AST para validar
docstrings e complementar assinaturas/descrições privadas. Os HTML são ignorados
pelo Git; a fonte versionada é o código documentado. Não exige banco ou broker
para gerar.

`--check` não importa o produto. `--html` importa módulos com suas dependências,
sem iniciar servidores, menus de laboratório ou migrations. A geração desabilita
o carregamento automático de dotenv. Não use `python -m pydoc -p` com exposição
na rede para consultar uma cópia com configuração privada.

Migrations são histórico versionado de schema, com os contratos `upgrade` e
`downgrade` de Alembic. Sua execução e revisão seguem [validação de migrations](../operations/validation.md).
Não integram o índice importável de produto, pois compartilham o nome do pacote
externo `alembic`. Testes e scripts shell são descritos no guia de validação.

## Mapa de responsabilidades

| Pasta/módulo | Responsabilidade e fronteira |
|---|---|
| `api/main.py` | Aplicação ASGI, routers, tratamento comum de erros e correlação |
| `api/router_*.py` | HTTP, paginação, dependências de sessão/permissão e tradução de erros |
| `api/schemas_*.py` | Contratos Pydantic de entrada e saída; validações de campos |
| `api/service_*.py` | Regras de cadastro, integridade, busca e operações transacionais |
| `api/database.py` | Engine e sessão criados sob demanda; sessão por requisição |
| `api/service_auth.py`, `senhas.py`, `config_auth.py` | Sessões opacas, Argon2id, política de senha e bloqueio |
| `api/permissoes.py`, `dependencias_auth.py` | Perfis, capacidades e autorização de rotas |
| `api/auditoria.py` | Contexto de autor/correlação e listener transacional de auditoria |
| `api/criar_admin.py`, `seed_*.py` | Bootstrap administrativo e cadastros iniciais |
| `db/models.py`, `base.py` | Entidades ORM e metadata compartilhada com migrations |
| `db/url.py`, `runtime.py` | Resolução de URLs, validação e engine de ingestão |
| `rfid_ingestion/config.py` | Settings, transporte MQTT, limites e parâmetros temporais |
| `rfid_ingestion/parsing.py`, `normalization.py`, `topics.py` | Envelope seguro, adapters, contrato canônico e tópicos |
| `rfid_ingestion/connection.py`, `mqtt_client.py` | Paho, TLS, sessões, threads, ACKs e recuperação |
| `rfid_ingestion/repository.py`, `persistence.py` | Leituras idempotentes no PostgreSQL e auditoria JSONL |
| `rfid_ingestion/reader_status.py`, `api/router_status_hardware.py` | Contato monotônico, heartbeat opcional, estados temporais e agregação segura de portais |
| `tools/reader_heartbeat.py` | Publicador independente para ensaio do contrato de heartbeat |
| `rfid_ingestion/resilience.py`, `health.py` | Taxonomia de falha, backoff e healthcheck |
| `rfid_ingestion/simulator.py`, `verification.py` | Publicador CLI e verificação de transporte |
| `rfid_inference/debounce.py` | Consolidação por EPC/antena, tolerância de event time e observações |
| `rfid_inference/passage*.py` | Detector de estados, topologia histórica, persistência e retries |
| `rfid_inference/direction*.py` | Evidências, direção confirmada/ambígua/desconhecida e recuperação |
| `rfid_movement/` | Ledger de movimentações, associação temporal e correção append-only |
| `rfid_location/` | Projeção temporal, bloqueio, reconciliação e classificação de recência |
| `tools/lab_launcher/` | Perfis, Compose, seed, sessão, terminais, observadores e publicador |
| `api/service_cadastro.py`, `api/router_cadastro.py` | Descoberta de EPCs detectados e cadastro atômico equipamento + tag |
| `api/simulacao/` | Simulador web: esquema do layout, presets EASY/HUPAA, aplicação da topologia, sessões, motor e publicador MQTT |
| `api/router_simulacao.py` | Layouts, sessões compartilhadas, itens virtuais e monitoramento |
| `api/ambiente.py`, `api/seguranca_http.py` | `APP_ENV`, cabeçalhos de segurança, verificação de Origin, CORS e travas de produção |
| `tools/limpeza_banco.py` | Limpeza segura de dados experimentais (prévia, execução, verificação) |
| `deploy/production/` | Imagens e Compose de referência para hospedagem |
| `scripts/dev.py` | Inicialização conjunta e encerramento de API, interface e launcher |
| `scripts/documentation.py` | Cobertura de docstrings e geração pydoc |

## Contratos essenciais

### Evento e persistência

`parsing.build_event` recebe tópico, QoS, retain, bytes e Settings. Produz envelope
com recepção UTC, conteúdo de auditoria e `canonical_event` ou motivos de rejeição.
`normalization.normalize` devolve `(evento, erros, leitor, adapter)`. O evento tem
`event_id`, `epc`, `antenna`, `reader_id`, `timestamp`, `rssi` e `metadata`.

`RawReadingRepository.persist_many` mantém a ordem de entrada nos resultados
`PersistenceResult`: `inserted`, `duplicate` ou `rejected`. Falhas de banco são
`PersistenceError` categorizadas. O receptor só envia ACK após sucesso/deduplicação
ou decisão terminal de rejeição; indisponibilidade transitória pausa consumo e
aciona recuperação. Confirmações de uma sessão antiga não são enviadas à nova.

### Transações e concorrência

Services da API recebem sessão SQLAlchemy e aplicam suas próprias fronteiras de
commit/rollback conforme o contrato da operação; routers traduzem exceções do
domínio. `get_db` garante fechamento da sessão. Operações de ledger que recebem
`Connection` não fazem commit: o chamador possui a transação.

`LocationProjectionService.process_passage` engloba ledger e projeção na mesma
transação, com lock do equipamento e proteção contra regressão temporal.
Correções manuais exigem justificativa e versão otimista do cadastro. Auditoria
participa da transação de negócio; consultas não editam a trilha persistida.

Índices e constraints protegem EPC ativo único, patrimônio normalizado, porta
ativa por leitor e vigências de topologia. As regras são verificadas contra
PostgreSQL; SQLite não reproduz esses contratos.

### Erros e segurança de diagnóstico

Não registre credenciais MQTT, URLs com senhas, cookies ou tokens. O launcher
sanitiza progresso/erros de subprocessos e mantém a configuração temporária em
`.lab_launcher/`, ignorada pelo Git. O ingestor filtra segredos conhecidos no
logging. Erros HTTP do domínio usam códigos coerentes com ausência, conflito,
validação e permissão. Não imprima uma exceção SQLAlchemy bruta em um novo caminho
de diagnóstico que possa incluir parâmetros.

## Frontend TypeScript

Pydoc documenta Python. A referência da interface está neste guia, nos tipos
TypeScript e nos comentários JSDoc próximos às regras compartilhadas.

| Área | Função |
|---|---|
| `frontend/src/App.tsx` e `pages/` | Navegação e composição de páginas operacionais |
| `services/dashboard.ts`, `admin.ts`, `auth.ts`, `correcoes.ts` | Contratos HTTP e tratamento de respostas |
| `services/live.tsx` | Consultas periódicas, cancelamento, retenção de dados e recuperação |
| `services/assetPriority.ts` | Grupos de prioridade e comparação natural estável |
| `services/mapTopology.ts` e `config/mapaConfig.ts` | Vínculo da planta esquemática com IDs e referências cadastrados |
| `components/mapa/` | Plantas, clusters ilustrativos, abas e leituras por equipamento |
| `components/equipamento/` | Detalhe, histórico e correção manual |
| `components/admin/`, `pages/AuditPage.tsx`, `pages/UsersPage.tsx` | Administração e consulta auditável |
| `types/dashboard.ts` | Tipos de ativos, leituras, resumo e filtros |
| `src/test/` | Contratos visuais, sessão, consultas e regras de ordenação |

`isFresh` usa 30 s para presença; `assetRank` não depende do volume de leituras.
Os mapas não calculam posição por RSSI: `clusterPositions` distribui IDs em uma
zona apenas para legibilidade. A atualização automática mantém as tabelas no
grupo correto sem trocar posições por diferenças no horário da leitura.

## Manutenção

Ao alterar uma regra, atualize a docstring na mesma mudança e registre problema,
importância e solução em `docs/implementations/`. Rode Ruff, verificações pertinentes
e `scripts/documentation.py --check`. Uma nova dependência de hardware não pode
ser declarada validada por um teste sintético. Consulte a [arquitetura](../architecture/system-overview.md)
para parâmetros, recuperação e limitações de durabilidade.
