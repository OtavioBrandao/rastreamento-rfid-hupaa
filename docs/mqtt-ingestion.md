# Ingestão MQTT — local e HiveMQ

O mesmo ingestor, simulador, payload e tópicos funcionam nos dois modos.
HiveMQ Cloud Serverless é o broker principal do MVP; Mosquitto é o ambiente
local/offline de desenvolvimento e contingência manual. **Aceite externo pendente.**
Veja a [decisão e comparação dos provedores](decisions/0002-managed-mqtt.md).

## Instalação (Ubuntu 24.04)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Python >= 3.10 e Paho `>=2.1,<3`, callbacks VERSION2, MQTT 3.1.1.
Os probes de segurança usam MQTT 5 para identificar negativas explícitas.
O ingestor não contém lógica específica de firmware.

## Configuração e seleção explícita

| Variável | Uso |
|---|---|
| `MQTT_MODE` | `local` (padrão de desenvolvimento) ou `cloud`; nunca muda automaticamente |
| `MQTT_HOST` | IP/hostname sem esquema ou credenciais; local aceita localhost, loopback e IP privado explícito |
| `MQTT_PORT` | 1883 local; 8883 obrigatório no modo cloud |
| `MQTT_TLS_ENABLED` | `false` local; `true` obrigatório cloud |
| `MQTT_USERNAME`, `MQTT_PASSWORD` | Definidos juntos; obrigatórios cloud; omitidos no Mosquitto anônimo |
| `MQTT_CLIENT_ID` | Identificador único por conexão; obrigatório explícito cloud; não é autenticação |
| `MQTT_TOPIC` | Filtro do ingestor ou tópico exato do simulador; perfis separados |
| `MQTT_CA_CERT` | Opcional: caminho para CA pública PEM; vazio usa autoridades confiáveis do sistema |
| `MQTT_KEEPALIVE` | 60 s por padrão; entre 1 e 65535 |
| `MQTT_QOS` | 1, fixado pelo contrato |
| `EVENTS_FILE` | `data/raw_events.jsonl` por padrão |
| `LOG_LEVEL` | INFO por padrão; DEBUG, WARNING, ERROR e CRITICAL também aceitos |
| `MQTT_MAX_PAYLOAD_BYTES` | Limite antes do parsing JSON; 65536 bytes por padrão |
| `RFID_DEFAULT_ADAPTER` | `ez700` por padrão; `simulator` para o formato alternativo |
| `RFID_READER_ADAPTERS` | Objeto JSON que mapeia reader_id para adapter; sobrepõe o padrão |
| `EZ700_TIMESTAMP_FORMAT` | `rfc3339` por padrão; `epoch_ms` somente por seleção explícita |

TLS valida certificado **e hostname**, mínimo TLS 1.2. Não há opção insegura.
Erros de rede, TLS, autenticação ou assinatura inicial encerram com código não
zero; não disparam conexão a outro broker. Reconexão após queda usa somente o
endpoint configurado. SUBACK deve conceder QoS 1. Falha de persistência encerra
com erro em vez de continuar dando aparência de coleta bem-sucedida.

A aplicação lê variáveis exportadas. `.env.example` é o exemplo local;
`.env.local.example` e `.env.cloud.example` são os perfis explícitos. Arquivos
reais `.env`, `.env.*`, chaves privadas e dados de execução são ignorados pelo Git.
Use um terminal por perfil para não herdar variáveis do outro modo.
Os exemplos abaixo usam Bash; arquivos carregados com `source` devem ser confiáveis.
Coloque valores especiais entre aspas simples e não use `set -x`.

### Local

```bash
cp .env.local.example .env.local
chmod 600 .env.local
docker compose up -d
set -a; source .env.local; set +a
python -m rfid_ingestion
```

O Compose mantém o listener da PoC em 1883 em todas as interfaces. Para
desenvolvimento somente no notebook: `MQTT_BIND_ADDRESS=127.0.0.1 docker compose up -d`.
Para leitores físicos, configure **no leitor** o IP LAN do computador que executa
o broker, substituindo `localhost`. Clientes em outro computador também usam esse
IP em `MQTT_HOST`. O ingestor no próprio notebook pode continuar com localhost.
Use `ip -4 -brief address show up` e verifique a rede com a TI. Não crie hotspot
no notebook, não encaminhe 1883 no roteador e não exponha esse listener à Internet.

**Acesso anônimo local é exclusivo de desenvolvimento em rede controlada.**
Foi preservado para não mudar o fluxo físico anterior nem exigir provisionamento
local de senhas nesta issue. Não comprova autenticação ou ACL. O cliente suporta
usuário/senha também no modo local, caso a equipe provisione Mosquitto autenticado.

### Cloud: criação manual e ACL

1. Entrar no painel HiveMQ e criar **Serverless**, não Starter pago. Selecionar a
   região disponível apropriada. Registrar data, plano e região sem segredos.
2. Em Overview / Connection Details, copiar o hostname e confirmar a porta 8883.
3. Em Access Management, criar **permissões customizadas**, conforme a tabela.
   As permissões padrão amplas (`#`) não atendem ao menor privilégio.
4. Criar três usuários com senhas independentes e fortes, associando uma permissão
   a cada usuário. Não reutilizar a credencial do ingestor nos simuladores/leitores.
5. Preencher os três arquivos privados descritos abaixo. Não exportar screenshots
   que mostrem senhas. O login/MFA e a criação do cluster são ações manuais pendentes.

| Identidade lógica | Client ID de exemplo | Permissão | Filtro/tópico |
|---|---|---|---|
| Ingestor | `easy-cloud-ingestor` | Subscribe somente | `easy/dev/hupaa/+/+/readings` |
| Leitor/simulador 1 | `easy-cloud-reader-01` | Publish somente | `easy/dev/hupaa/portal-01/reader-01/readings` |
| Leitor/simulador 2 | `easy-cloud-reader-02` | Publish somente | `easy/dev/hupaa/portal-01/reader-02/readings` |

Negar tudo que não for permitido. Leitores não assinam; ingestor não publica
e não recebe outros ambientes/sites. Serverless permite uma permissão por
credencial; as roles avançadas são de planos superiores. Client ID não é segredo
nem prova de quem publicou. Duas conexões com o mesmo ID podem se derrubar.
As [regras oficiais](https://docs.hivemq.com/hivemq-cloud/authn-authz.html)
orientam a criação de permissões customizadas e o comportamento do cache.

```bash
cp .env.cloud.example .env.cloud
cp .env.cloud.example .env.cloud.reader-01
cp .env.cloud.example .env.cloud.reader-02
chmod 600 .env.cloud .env.cloud.reader-01 .env.cloud.reader-02
# Editar os três arquivos fora do Git: endpoint, credencial individual,
# Client ID e MQTT_TOPIC conforme a tabela acima.
```

Ingestor, em seu terminal:

```bash
set -a; source .env.cloud; set +a
python -m rfid_ingestion
```

O mesmo comando com `.env.local` seleciona manualmente Mosquitto. Pare a sessão
anterior antes de trocar. Falta de Internet deixa cloud com erro; não existe fallback.

## Contrato e migração

Formato único: `easy/<environment>/<site_id>/<portal_id>/<reader_id>/readings`.
Identificadores usam letras, números, `_` e `-`; IDs lógicos como `reader-01`
independem de EZ700, fabricante ou número de série. O filtro geral suportado é
`easy/+/+/+/+/readings`; prefira o filtro restrito ao ambiente/site na ACL e no ingestor.

Migrar cada configuração `rfid/<reader-id>/tags` para o novo tópico e trocar o
filtro do ingestor **na mesma sessão de validação**. Atualizar ACL e simuladores.
O código novo rejeita o padrão antigo; não existe assinatura dupla silenciosa.
JSONLs históricos continuam legíveis pelo parser. Para reproduzir o transporte
antigo, usar a revisão anterior, sem misturar essa evidência com a validação atual.

Payload preservado, baseado na fixture existente:

```json
{"epc":"E2801190A502006016C32F62","tid":"E280119020004F62B6190300","timestamp":"1632759395291","rssi":-3880,"phase":49,"channel":906250,"antenna":1,"readerid":"reader-01"}
```

O exemplo numérico exige `EZ700_TIMESTAMP_FORMAT=epoch_ms` para normalização
sintética; a semântica física ainda precisa de confirmação. O padrão aceita
RFC3339 com fuso explícito. A origem lógica vem do tópico; identidade divergente
no payload rejeita o evento canônico. Campos extras ficam em metadata, RSSI EZ700
permanece bruto e o campo canônico em dBm fica nulo. Contrato completo, validações,
seleção explícita e limites em [normalização RFID](rfid-normalization.md).

JSONL mantém `received_at_utc`, `topic`, `qos`, `retain`, `payload_original`,
`payload_encoding`, `payload_json`, `parse_error`; acrescenta `validation_errors`,
`canonical_event`, `reader_id` e `adapter`.
Mensagens incompletas também são gravadas, com erros de validação, sem derrubar
o ingestor. Bytes inválidos continuam em base64. QoS 1 permite duplicação; não
há deduplicação nem garantia de exatamente uma vez, nem fila durável offline.
`retain=false` é usado em toda publicação do simulador.

## Simulador único

Local em outro terminal, sem importar o perfil do ingestor:

```bash
MQTT_MODE=local MQTT_HOST=localhost MQTT_PORT=1883 MQTT_TLS_ENABLED=false \
MQTT_CLIENT_ID=easy-local-reader-01 MQTT_TOPIC=easy/dev/hupaa/portal-01/reader-01/readings \
python -m rfid_ingestion.simulator --reader-id reader-01 --count 20 --interval 0.1
```

Para dois publicadores externos simultâneos (mesma máquina, credenciais distintas):

```bash
(set -a; source .env.cloud.reader-01; set +a
 python -m rfid_ingestion.simulator --reader-id reader-01 --antenna 1 --count 20 --interval 0.2) &
p1=$!
(set -a; source .env.cloud.reader-02; set +a
 python -m rfid_ingestion.simulator --reader-id reader-02 --antenna 2 --count 20 --interval 0.2) &
p2=$!
wait "$p1"; wait "$p2"
```

`--epc`, `--antenna`, `--timestamp` permitem fixtures determinísticas; `--count`
e `--interval` controlam quantidade/frequência; `--invalid json` e
`--invalid missing` reproduzem erros. `--environment`, `--site-id`, `--portal-id`
e `--reader-id` constroem o tópico quando `MQTT_TOPIC`/`--topic` não for informado.
O leitor lógico deve coincidir com o tópico. Senhas nunca são argumentos de CLI.
`--format simulator` publica o formato alternativo (`tag`, `port`, `signal`,
`observed_at`). Configure o adapter correspondente no ingestor. O padrão
`--format ez700` preserva a estrutura anterior, mas o relógio sintético agora
publica RFC3339 UTC; `--timestamp` continua permitindo replay explícito.
PUBACK MQTT 3.1.1 isolado não prova entrega: conferir sempre o JSONL do ingestor.

## Testes e comando de aceite

```bash
python -m unittest discover -s tests -v
bash tests/reader-connectivity/mqtt/smoke-test.sh
```

O smoke usa Compose isolado, loopback e porta 18884, testa dois publicadores,
40 mensagens válidas e 2 inválidas, verifica JSONL e encerra seu contêiner.
Para broker local já iniciado: `RUN_MQTT_INTEGRATION=1 python -m unittest discover -s tests -v`.
`TEST_MQTT_PORT` altera a porta da integração. Testes sem broker pulam somente a integração.
Os três testes de handshake TLS usam OpenSSL (certificado efêmero em diretório
temporário); se o executável não estiver instalado, são explicitamente pulados.
Eles validam o transporte TLS local, não o serviço HiveMQ.

Após provisionar o HiveMQ, pare qualquer ingestor com o mesmo Client ID e execute:

```bash
python -m rfid_ingestion.verification \
  --env-file .env.cloud \
  --publisher-env .env.cloud.reader-01 --publisher-env .env.cloud.reader-02 \
  --count 20 --interval 0.2 --seconds 15 --network rede-casa \
  --security --report data/iss001-hivemq-simuladores.json
```

O comando valida perfis sem executar shell, resolve DNS, verifica TLS, inicia o
ingestor, exige SUBACK, inicia dois simuladores, correlaciona mensagens pelo
timestamp sintético da execução e verifica JSONL. Usa um arquivo JSONL novo em
`data/verification-<id>.jsonl` para não reaproveitar evidência antiga.
Em seguida testa senha aleatória inválida, publicação do leitor no tópico alheio,
assinatura do leitor, publicação do ingestor e assinatura fora do filtro.
Só uma negativa explícita apropriada comprova autenticação/ACL; timeout é
**inconclusivo**, nunca aprovado. Alguns brokers aceitam SUBSCRIBE mas filtram
entrega: nesse caso o probe não valida a ACL e exige investigação/evidência adicional.
Esperar propagação das permissões antes de repetir; não aceitar ausência de mensagem sozinha.

O retorno 0 indica sucesso das etapas solicitadas, não conclusão da issue.
Sem `--security`, segurança fica pendente. Nunca use o modo local como evidência
de TLS ou redes distintas. Relatório sanitizado contém Client IDs **configurados**,
tópicos, EPCs, antenas, timestamps, contagens e taxa aproximada. MQTT não entrega
o Client ID do publicador ao assinante; hardware exige conferência no leitor/painel.
Logs não incluem payload, senha, username ou tracebacks de erros operacionais.
JSONL bruto continua preservando dados de origem; nunca publique segredos no payload.

Veja [visita curta e duas redes](experiments/iss001-managed-validation.md) e
[matriz de evidências](evidence/iss001/README.md).

## Rotação e contingência

1. Criar nova credencial no painel.
2. Associar a mesma ACL restrita correta.
3. Atualizar somente o arquivo privado/dispositivo correspondente.
4. Encerrar a conexão antiga, conectar novamente e validar entrega/JSONL.
5. Revogar a credencial antiga.
6. Forçar nova tentativa com a antiga e confirmar rejeição explícita.
7. Registrar data, identidade lógica e resultado sem senha.

A remoção de credenciais não encerra automaticamente conexões existentes;
o cache de credenciais pode durar 1 minuto, o de permissões 5 minutos. Confirmar
reconexão efetiva antes de considerar a rotação validada.

Contingência controlada: parar ingestor/publicadores cloud, iniciar Compose,
carregar os perfis locais em novos terminais, apontar dispositivos para o IP LAN,
rodar simuladores e conferir JSONL. Registrar a mudança de modo e depois retornar
explicitamente ao HiveMQ. Não há ponte implementada nesta issue.
