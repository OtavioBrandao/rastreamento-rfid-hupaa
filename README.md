# RFID Hospital MVP

MVP experimental para rastreabilidade aproximada por zonas de equipamentos
hospitalares do HUPAA/UFAL usando RFID UHF passivo. A posição será inferida
pela última passagem confirmada em uma zona, não por posicionamento contínuo.

## Fase atual — ISS-005 sobre a infraestrutura da ISS-001

**HiveMQ Cloud Serverless é o broker principal escolhido para o MVP.** O código
suporta modo externo com TLS e modo local com Mosquitto, usando o mesmo ingestor,
simulador, contrato e JSONL. **A Issue #1 foi encerrada em 05/09/2026**, com cluster,
credenciais, TLS e ACLs configurados. O [registro de validação da equipe](https://github.com/OtavioBrandao/rfid-hospital-mvp/issues/1#issuecomment-5553433705)
relata testes com simuladores: 20/20 mensagens no Mosquitto local, 40/40 no HiveMQ
e 200/200 via HiveMQ entre duas redes distintas. As evidências locais versionadas
preservam o estado anterior dessa data; o aceite com EZ700 físico e a rede do
hospital permanece **PENDENTE DE VALIDAÇÃO FÍSICA**.

```text
leitor ou simulador → HiveMQ com TLS → ingestor Python/Paho → data/raw_events.jsonl
                    ou, por seleção manual de desenvolvimento:
leitor ou simulador → Mosquitto local → mesmo ingestor → JSONL
```

Não há fallback automático nem ponte entre brokers. O notebook executa o ingestor
e pode executar o broker local; **não funciona como hotspot**. Desenvolvimento,
testes unitários, integração e fixtures não dependem de acesso ao laboratório.

## Execução rápida local (Ubuntu 24.04)

```bash
cp .env.local.example .env.local
docker compose up -d
set -a; source .env.local; set +a
# Perfil explícito para timestamps gerados pelo nosso simulador ez700.
EZ700_TIMESTAMP_FORMAT=epoch_ms python -m rfid_ingestion
make local-up
make status-local
```

Isso inicia PostgreSQL, Mosquitto, aplica as migrations atuais e só então inicia o
ingestor. O perfil é totalmente local/offline. Para publicar três eventos:

```bash
make simulator-local
tail -n 3 data/raw_events.jsonl
```

Para parar sem apagar o banco: `make stop-local`. O reset exige confirmação e
remove somente o volume PostgreSQL local:
`CONFIRM_RESET_LOCAL=APAGAR make reset-local`.

```bash
make tests
make smoke
```

O smoke executa um broker isolado em loopback:18884 e dois simuladores,
incluindo mensagens inválidas. Ele verifica o pipeline local; o registro acima
documenta separadamente TLS, autenticação e ACL no HiveMQ com simuladores.
O modo gerenciado usa `.env.cloud` e `make managed-up`; não inicia Postgres nem
Mosquitto locais. Ele consome as convenções `DATABASE_URL`/`APP_DATABASE_URL` da
ISS-002b e o Alembic da ISS-002c. Credenciais reais permanecem fora do Git; a
persistência de eventos em banco pertence à ISS-006.

Veja o [guia completo da ISS-003](docs/infrastructure/iss-003-docker-compose.md)
para arquitetura, variáveis, comandos equivalentes sem Make, evidências, reset,
pendências e troubleshooting. A execução direta no host continua documentada em
[Ingestão MQTT](docs/mqtt-ingestion.md).

## Qualidade e CI

Pushes para `main` e Pull Requests direcionados a ela executam jobs separados de
lint, testes e migrations. Para reproduzir as verificações básicas localmente:

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check --select E4,E7,E9,F .
python -m ruff check --select I .
python -m pytest -q
```

O job `Migrations` reutiliza a validação rigorosa da ISS-002c em PostgreSQL
descartável: aplica duas vezes, reverte, reaplica e confere o schema. Os comandos
locais e a interpretação das falhas estão no [guia da
ISS-004](docs/infrastructure/iss-004-ci.md).

## Contrato atual

Tópico: `easy/<environment>/<site_id>/<portal_id>/<reader_id>/readings`.
Exemplo: `easy/dev/hupaa/portal-01/reader-01/readings`.
IDs são lógicos e independentes de fabricante; uma credencial e Client ID por cliente.
O ingestor pode assinar `easy/+/+/+/+/readings`; o perfil fornecido restringe
a `easy/dev/hupaa/+/+/readings` para combinar com a ACL do MVP.

Adapters explícitos convertem EZ700 e simulador em um evento canônico com
`event_id`, `epc`, `rssi`, `antenna`, `reader_id`, `timestamp` UTC e `metadata`.
QoS 1, retain falso. O ingestor preserva payload original, JSON, metadados e
erros no JSONL; acrescenta `canonical_event` (nulo quando rejeitado).
O RSSI EZ700 mantém a unidade pendente e o valor bruto em metadata; timestamp
numérico exige configuração explícita. Veja o [contrato e adapters](docs/rfid-normalization.md).
JSON inválido e bytes não UTF-8 continuam preservados. Não há deduplicação,
banco, inferência de passagem ou dashboard nesta issue.

O transporte antigo `rfid/<reader-id>/tags` foi substituído explicitamente.
As configurações dos leitores precisam migrar antes da próxima coleta.
JSONLs históricos continuam preservados; não se assinam os dois padrões em silêncio.

## Guias e evidências

- [Operação local/cloud, cluster, ACL, simuladores e rotação](docs/mqtt-ingestion.md).
- [Contrato canônico, adapters e validação sintética da ISS-005](docs/rfid-normalization.md).
- [Relatório de entrega e testes da ISS-005](docs/evidence/iss005/README.md).
- [Comparação HiveMQ × EMQX e estimativas de volume](docs/decisions/0002-managed-mqtt.md).
- [Visita curta ao laboratório e comandos para duas redes](docs/experiments/iss001-managed-validation.md).
- [Resultados reais e matriz de aceite da ISS-001](docs/evidence/iss001/README.md).
- [Experimento anterior de redes locais](docs/experiments/mqtt-network-validation.md).

## Validação física anterior (histórico, não evidência de HiveMQ)

A comunicação MQTT em rede cabeada já foi validada com dois Identix EZ700,
Client IDs `EZ700-82-8A-54` e `EZ700-82-89-14`, publicando em
`rfid/EZ700-82-8A-54/tags` e `rfid/EZ700-82-89-14/tags`.
Foram observados DHCP, recepção no Mosquitto e no ingestor, persistência JSONL,
separação dos leitores e simulação de movimentação de tag entre duas zonas.
Consulte o [registro de laboratório](docs/test1_readers_communication.pdf).

O Wi-Fi institucional não foi concluído por falha na obtenção de IP; o hotspot
móvel não pôde ser usado por falta de sinal. Permanecem pendentes Wi-Fi estável,
sub-redes, regras da TI, estabilidade prolongada e validação do firmware para
TLS, certificado, 8883, usuário/senha e Client ID configurável.
Essas pendências de hardware/campo não impedem o desenvolvimento do software.

O ingestor é permanente na arquitetura e poderá futuramente alimentar banco,
backend e dashboard. JSONL permite auditoria e reprodução; não substitui o banco
nem garante entrega offline ou exatamente uma vez.

## Materiais do projeto

[Google Drive — RFID Hospital MVP](https://drive.google.com/drive/folders/1AYqcT6jRI6UQNMan_DnyVXhEiNwMNgse?hl=pt-br)
