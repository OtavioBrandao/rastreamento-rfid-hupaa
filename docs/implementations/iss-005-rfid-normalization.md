# ISS-005 — contrato canônico e adapters RFID

## Pipeline e limites

O mesmo cliente Paho/Settings da ISS-001 recebe em local ou cloud, preserva o
envelope bruto, valida tamanho/UTF-8/JSON, resolve contexto e adapter, normaliza
e grava JSONL append-only. A [ISS-006](iss-006-raw-readings-persistence.md) acrescenta
PostgreSQL e ACK manual ao mesmo consumidor. Não há debounce, inferência de
passagem ou alteração de ACL. O notebook não é hotspot.

O tópico exclusivo continua `easy/<environment>/<site_id>/<portal_id>/<reader_id>/readings`.
Não foi criado alias legado. JSONLs históricos continuam legíveis; chamar o
parser com tópico antigo preserva a evidência, mas não gera evento canônico.
`reader_id` vem sempre do tópico validado; `readerid` e `reader_id` no payload são
opcionais, mas cada um, se presente, deve ser exatamente igual ao tópico.
Essa identidade lógica não autentica o publicador; autenticação e ACL são do broker.

## Contrato v1

Todos os campos abaixo estão presentes no `canonical_event`, exceto que
consumidores não devem exigir metadata. Um envelope rejeitado tem
`canonical_event: null`. O JSONL conserva todos os campos de auditoria da ISS-001.

| Campo | Tipo e semântica |
|---|---|
| `event_id` | String `sha256:` + 64 caracteres hexadecimais, identificação determinística da mensagem de origem |
| `epc` | String não vazia após verificação de espaços; valor preservado, sem impor tamanho/encoding do fabricante |
| `rssi` | Número finito em dBm, <= 0, ou `null` quando unidade não comprovada; nunca inventar escala |
| `antenna` | Inteiro positivo, booleanos rejeitados; sem máximo físico presumido |
| `reader_id` | String lógica extraída do tópico oficial |
| `timestamp` | String UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ`, precisão máxima de microssegundos |
| `metadata` | Objeto opcional de dados de origem; emitido pelos adapters atuais |

Metadata contém `adapter`, `source_fields` (campos extras), `rssi_original`,
`rssi_unit` (`dBm` ou `unknown`), `timestamp_original` e `timestamp_format`.
Não usar campos de fabricante para lógica de domínio. `null` em RSSI significa
unidade desconhecida, não ausência de leitura nem intensidade zero.

## Seleção e extensão

As opções pertencem ao `Settings` existente e não alteram transporte/TLS:

```bash
export RFID_DEFAULT_ADAPTER=ez700
export RFID_READER_ADAPTERS='{"reader-02":"simulator"}'
export MQTT_MAX_PAYLOAD_BYTES=65536
export EZ700_TIMESTAMP_FORMAT=rfc3339
```

O mapa por reader_id tem precedência sobre o adapter padrão; não há detecção
por campos do payload. Reader IDs usados no mapa devem ser únicos no conjunto
de tópicos assinado, inclusive entre sites. Adapter desconhecido rejeita a
mensagem com motivo explícito e preserva JSONL, permitindo outros leitores.

Para estender, criar função em `normalization.py` (ou importar de módulo próprio),
registrar em `ADAPTERS`, testar e configurar seu nome. A função recebe
`(payload, settings)` e retorna `(epc, antenna, rssi_original, timestamp_original,
unit, epoch_ms, extras)`. O núcleo valida esses valores e gera evento/ID.
Erros de validação usam mensagens fixas sem conteúdo do payload; extensões não
devem incluir valores recebidos em exceções. Falhas inesperadas são registradas
como `falha interna do adapter`, sem traceback ou dados da exceção.

## EZ700 e timestamps

Referência: `tests/fixtures/identix/tag-read.json`, mantida intacta:

```json
{"epc":"E2801190A502006016C32F62","tid":"E280119020004F62B6190300","timestamp":"1632759395291","rssi":-3880,"phase":49,"channel":906250,"antenna":1,"readerid":"EZ700-PORTAL-01"}
```

Após a validação física relatada em 25/09/2026, timestamps numéricos do EZ700
são tratados como contadores do dispositivo, não como datas. Inteiros não
negativos e strings de dígitos usam `received_at_utc` do envelope MQTT como
timestamp canônico. Chamadas diretas à normalização sem esse envelope usam o
horário UTC atual. O valor original permanece em metadata, com
`timestamp_format: received_at_utc`.

Isso também se aplica à fixture histórica de 13 dígitos e à configuração legada
`EZ700_TIMESTAMP_FORMAT=epoch_ms`: números do EZ700 não são mais interpretados
como Unix epoch. Para replay com data absoluta, fornecer RFC3339 explícito.
Veja o [hotfix de compatibilidade física](hotfix-ez700-contador-timestamp.md).

**PENDENTE DE VALIDAÇÃO FÍSICA:** unidade/escala do RSSI. `-3880` e `-5725`
permanecem em metadata e o RSSI canônico fica nulo. Não dividimos por 100.

RFC3339 exige data/hora com `T`, segundos, `Z` ou offset explícito e de zero a
seis casas decimais. Converte offset para UTC, valida calendário e rejeita data
sem timezone, formatos desconhecidos, leap second e precisão superior. Essa
validação também se aplica ao horário de recepção usado pelo EZ700. Timestamp
ausente ou inválido continua rejeitado; somente contadores inteiros não negativos
recebem o tratamento específico do EZ700.

## Simulador alternativo e equivalência

```json
{"tag":"E2801190A502006016C32F62","port":1,"observed_at":"2021-09-27T13:16:35.291-03:00","signal":{"value":-3880,"unit":"unknown"},"reader_id":"EZ700-PORTAL-01"}
```

Com adapter `simulator`, esse exemplo produz os mesmos `epc`, `antenna`, `rssi`
e `reader_id` da fixture; seu timestamp absoluto é preservado, enquanto a fixture
EZ700 usa a recepção. Metadata e event_id diferem, pois identificam origens diferentes. `signal` é preservado integralmente
em metadata, inclusive campos extras. O CLI `--format simulator` gera por padrão
`signal: {"value": -38.8, "unit": "dBm"}`; esse valor sintético já declara unidade.
O simulador padrão (`--format ez700`) mantém a estrutura da fixture histórica e
gera `str(time.time_ns() // 1_000_000)`: timestamp numérico em string, em
milissegundos desde Unix epoch do relógio do próprio simulador. O adapter EZ700 agora trata também esse número sintético como contador e usa
o horário de recepção, independentemente do perfil legado. O formato alternativo `--format simulator` continua gerando RFC3339 UTC.
`--timestamp` preserva literalmente o valor informado em ambos os formatos.
Nenhum desses comportamentos comprova o timestamp do equipamento físico.

## Identidade com QoS 1

SHA-256 sobre a concatenação de `rfid-v1`, tópico completo, nome do adapter,
formato de timestamp efetivamente usado e bytes originais, separados por NUL.
Não entram horário de recepção, packet ID, retain ou estado DUP. Reentrega dos
mesmos bytes no mesmo contexto e configuração produz o mesmo ID após restart.
Tópico completo evita colisão lógica entre ambientes, sites e portais.

É identidade de mensagem, não deduplicação semântica: whitespace, ordem dos
campos, extras ou representação numérica diferentes alteram o ID. Duas leituras
legítimas de bytes idênticos no mesmo tópico também terão ID igual. Futuramente
sequência/ID confiável de origem pode demandar nova versão desse contrato.
Não há garantia exactly-once. A ISS-006 persiste esse ID com idempotência;
a ISS-014 continua responsável pelo debounce. O hotfix do contador usa o discriminador `received_at_utc` no hash para separar
a nova semântica dos IDs antigos calculados com `epoch_ms`; revisar replay histórico.
Reentregas mantêm o ID, embora o timestamp de recepção possa mudar. A persistência
idempotente conserva a primeira leitura gravada.

## Rejeição e auditoria

Payload inválido continua no JSONL: texto UTF-8 original ou base64 para bytes
inválidos. Campos `parse_error` e `validation_errors` explicam a rejeição;
validação canônica informa o primeiro erro encontrado. Payload acima de
`MQTT_MAX_PAYLOAD_BYTES` (inteiro positivo; padrão 65536) não é desserializado:
`payload_json` fica nulo, mas a evidência original é preservada integralmente.
O limite reduz trabalho de parsing, não tamanho da auditoria nem alocação pelo Paho.

JSON não objeto, número não finito/overflow, profundidade >64, campos faltantes,
tipos incorretos, EPC vazio, antena não positiva, RSSI inválido, timestamp inválido,
identidade conflitante e adapter inexistente não geram evento. JSONL escapa
Unicode (inclusive surrogate isolado), preservando valores após leitura e
evitando falha de encoding na persistência. Campos extras válidos são aceitos.

Log de normalização usa objeto JSON com `event_type`, `reader_id`, `adapter`,
`result`, `reasons` e `event_id`, após persistir a auditoria. A formatação global
de logging existente mantém seu prefixo. Não registra payload completo,
credenciais, certificados ou traceback. Falha real de escrita permanece fatal,
como na ISS-001; mensagens inválidas não interrompem o consumidor.

## Reprodução local (Ubuntu 24.04)

```bash
python -m pytest -q
bash tests/reader-connectivity/mqtt/smoke-test.sh
# Com Mosquitto local já iniciado:
RUN_MQTT_INTEGRATION=1 python -m pytest -q
```

O smoke inicia Mosquitto/PostgreSQL em Compose isolado, roda a suíte e limpa
seus recursos descartáveis. A execução direta exige TEST_DATABASE_URL para banco
de teste e RUN_MQTT_INTEGRATION=1 para broker. Nenhuma topologia é criada em runtime. A integração anterior conserva 40 mensagens válidas e duas inválidas;
a nova integração publica EZ700 e simulator simultaneamente, reapresenta bytes,
compara campos relevantes e confirma IDs distintos por leitor e estáveis no replay.
Testes unitários comparam também equivalência mantendo o mesmo reader_id.

Para inspecionar manualmente, iniciar Mosquitto e ingestor em um terminal:

```bash
docker compose up -d
EZ700_TIMESTAMP_FORMAT=epoch_ms RFID_READER_ADAPTERS='{"reader-02":"simulator"}' python -m rfid_ingestion
```

Em outro terminal (perfil local e ambiente virtual, sem MQTT_TOPIC do ingestor):

```bash
python -m rfid_ingestion.simulator --reader-id reader-01 --format ez700 --count 3
python -m rfid_ingestion.simulator --reader-id reader-02 --format simulator --count 3
```

Inspecionar `data/raw_events.jsonl`. Esses comandos demonstram os formatos e
RSSIs diferentes; a equivalência exata é verificada pela integração acima.
Cloud continua usando os mesmos Settings, CA/TLS, autenticação, assinatura e
QoS 1. Nenhum teste desta issue requer HiveMQ nem representa validação física.

O alinhamento com a ISS-006 foi concluído: RSSI pode permanecer nulo quando a unidade física não está comprovada, e o `event_id` canônico determinístico continua sendo a identidade usada para idempotência de mensagem.
