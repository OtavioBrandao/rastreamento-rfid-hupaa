# Hotfix — cadastro manual de tags físicas e MQTT sem TLS no broker externo

## Problema e importância para o MVP

No ensaio de 05/10/2026, o EZ700 físico publicou no Mosquitto local
(`easy/dev/hupaa/portal-01/reader-01/readings`). As leituras chegaram ao
ingestor, foram gravadas em `leituras_brutas` e apareceram nas leituras ao vivo
do frontend, mas o dashboard não mostrava nenhum equipamento: nenhum EPC lido
estava associado a um equipamento. Sem esse vínculo, não há movimentação nem
última zona, e o ensaio físico não pode ser acompanhado pela interface.

Além disso, as opções 2 e 3 do launcher (leitor físico) perguntavam um roteiro
sintético (1–3), o que não se aplica a um leitor real: o que importa no
laboratório é saber quais etiquetas estão em teste e a que equipamento cada uma
corresponde.

Por fim, a configuração do leitor com `mqtts` no HiveMQ Cloud não funcionou no
laboratório, e a equipe quer testar `mqtt` sem TLS. O ingestor recusava
qualquer broker externo sem TLS na porta 8883.

## O que foi feito

### Cadastro das tags no lugar do roteiro (opções 2 e 3)

Com leitor físico, o launcher não pergunta mais o roteiro. Depois das
migrations, quando o banco já está acessível, ele lista os EPCs lidos nas
últimas 24 horas (quantidade, último horário e equipamento já vinculado) e
pergunta, em sequência:

```text
EPC: 1                       ← número da lista ou EPC completo
Nome do equipamento para 3034000000000C40000000E8: Bomba de infusão 01
EPC: 3034000000000C400000012F
Nome do equipamento para 3034000000000C400000012F: Monitor multiparâmetro
EPC:                         ← vazio conclui
```

Sem menu, use `--tag EPC=Nome` uma vez por etiqueta:

```bash
python -m tools.lab_launcher start --env local --source physical \
  --tag "3034000000000C40000000E8=Bomba de infusão 01" \
  --tag "3034000000000C400000012F=Monitor multiparâmetro"
```

O seed cria o tipo **Equipamento físico de laboratório RFID**, um equipamento
por EPC com identificador interno `LAB-RFID-<EPC>` e o vínculo ativo da tag.
Ao repetir o ensaio, o vínculo é reaproveitado e o equipamento criado pelo
launcher é renomeado se o nome mudar. Uma tag já vinculada a um equipamento
cadastrado fora do laboratório (outro identificador) não é alterada. `--scenario`
e `--epc` continuam exclusivos dos testes sintéticos.

Leituras gravadas antes do cadastro continuam em `leituras_brutas`, mas não
geram movimentação retroativa: a última zona aparece após a próxima passagem
confirmada pelo portal.

### Transporte MQTT do broker externo (opções 3 e 4)

No broker externo, o launcher pergunta o transporte:

1. `mqtts` com TLS (8883, HiveMQ Cloud) — comportamento anterior;
2. `mqtt` sem TLS (1883) — somente para ensaio de laboratório.

Sem menu: `--mqtt-transport tls|plain`. No modo `plain`, o broker vem de
`MQTT_PLAIN_HOST`/`MQTT_PLAIN_PORT` (padrão 1883) e, se o broker exigir,
`MQTT_PLAIN_USERNAME`/`MQTT_PLAIN_PASSWORD`, todos em `config/environments/.env.cloud` (ignorado
pelo Git). Se `MQTT_PLAIN_HOST` faltar, o launcher pergunta, sugerindo
`broker.hivemq.com`. O banco externo (`DATABASE_URL`/`APP_DATABASE_URL`) e a
configuração TLS existente não mudam.

**Limitação importante:** clusters HiveMQ Cloud (`*.hivemq.cloud`) aceitam
somente TLS (8883) ou WebSocket com TLS (8884). Configurar o leitor com `mqtt`
na porta 1883 desse cluster deve ser recusado; o launcher avisa e pede
confirmação nesse caso. Para testar sem TLS é preciso outro broker, como o
broker público `broker.hivemq.com:1883`, que não tem autenticação: qualquer um
pode ler ou publicar no mesmo tópico. Use apenas EPCs de laboratório.

No ingestor, `MQTT_MODE=cloud` sem TLS só é aceito com o opt-in explícito
`MQTT_INSECURE_LAB=true` (e `MQTT_TLS_ENABLED=false`); nesse caso usuário e
senha são opcionais. Sem o opt-in, as regras anteriores continuam valendo
(TLS, 8883, usuário e senha). O Compose `ingestor-managed` repassa
`MQTT_TLS_ENABLED` e `MQTT_INSECURE_LAB`, com padrões `true` e `false`.

## Configuração do leitor para o teste sem TLS

- Host: o mesmo de `MQTT_PLAIN_HOST` (ex.: `broker.hivemq.com`), porta 1883,
  sem TLS.
- Tópico de publicação: `easy/dev/hupaa/portal-01/reader-01/readings`, o mesmo
  usado no teste local.
- Usuário e senha: vazios no broker público.

## Validação

- `python -m ruff check --config config/ruff.toml --select E4,E7,E9,F,I .`
- `python -m pytest -q` com `TEST_DATABASE_URL` apontando para um PostgreSQL
  descartável (não o banco do ensaio em andamento: a suíte apaga tabelas).
- Testes novos: cadastro e renomeação de equipamentos por tag, preservação de
  equipamento não laboratorial, `--tag` e perguntas interativas, transporte
  `plain` no launcher e opt-in `MQTT_INSECURE_LAB` no ingestor.

A conexão do EZ700 sem TLS ao broker externo permanece **PENDENTE DE VALIDAÇÃO
FÍSICA**.
