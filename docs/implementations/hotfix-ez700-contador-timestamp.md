# Hotfix — compatibilidade da ingestão com o EZ700 físico

## Problema e importância para o MVP

Na validação física relatada em 25/09/2026, o tópico
`easy/dev/hupaa/portal-01/reader-01/readings` recebeu o payload:

```json
{"epc":"007411B0A503007A91948576","rssi":-5725,"antenna":1,"timestamp":"1166264"}
```

O transporte MQTT funcionava, mas a normalização exigia RFC3339 e rejeitava o
contador do dispositivo, impedindo a persistência em `leituras_brutas`.

## Correção

Somente no adapter `ez700`, inteiros não negativos e strings de dígitos usam o
horário de recepção MQTT como timestamp canônico UTC. O parser apenas encaminha
o `received_at_utc` já registrado no envelope à normalização; chamadas diretas
sem horário usam UTC atual. A validação RFC3339 global permanece intacta e valida
também esse horário. Valores ausentes, booleanos, negativos, fracionários ou
textos inválidos continuam rejeitados. Outros adapters não aceitam contadores.

O contador original é preservado em metadata e `timestamp_format` passa a ser
`received_at_utc`. RFC3339 continua aceito pelo EZ700 e pelo simulador.
Não há mudança no banco, transporte ou persistência.

O código, a fixture e os testes anteriores declaram a unidade do RSSI desconhecida.
Não há convenção comprovada de centi-dBm: `rssi` continua nulo, com `-5725` em
`metadata.rssi_original` e `rssi_unit: unknown`. Converter para `-57.25` exige
confirmação física da unidade/escala.

## Compatibilidade e limites

- O perfil legado `EZ700_TIMESTAMP_FORMAT=epoch_ms` continua sendo aceito pela
  configuração, mas não transforma números do EZ700 em datas, mesmo com 13 dígitos.
  Replays sintéticos que precisam preservar data devem fornecer RFC3339.
- O hash usa o novo discriminador de formato; replays de mensagens antes gravadas
  como epoch_ms terão IDs diferentes. Reentregas dentro da nova semântica mantêm
  o ID, independentemente do horário de recepção, preservando idempotência.
- O horário representa recepção, não leitura física; atrasos de rede, fila e
  relógio do ingestor afetam o tempo utilizado nas etapas posteriores.
- Reinicialização do contador pode produzir bytes idênticos aos de leituras
  anteriores; a limitação preexistente da identidade por bytes permanece.

## Validação

Testes cobrem o payload físico, contadores em string e inteiro, ambos os perfis
legados, RFC3339 UTC gerado, fallback de relógio, timestamp de recepção inválido,
RSSI desconhecido, payloads inválidos, isolamento de outros adapters e ID estável.
A integração MQTT compara o timestamp EZ700 com a recepção e mantém a verificação
de RFC3339 absoluto do simulador.

Execução deste hotfix:

- `.venv/bin/python -m pytest -q tests/test_normalization.py tests/test_parsing.py`:
  22 aprovados e 48 subtestes aprovados.
- `.venv/bin/python -m pytest -q`: 845 aprovados, 2 ignorados, 85 subtestes
  aprovados e 4 avisos de dependências/migrations. As duas integrações MQTT
  opt-in não foram habilitadas nesta execução.
- Ruff (`E4,E7,E9,F,I`) nos quatro arquivos Python alterados e
  `git diff --check`: aprovados.

Não houve implantação/reinício do ingestor nem nova leitura física executada
por este hotfix; a aceitação do payload informado foi verificada nos testes.
