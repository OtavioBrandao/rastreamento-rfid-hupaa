# ISS-005 — relatório de entrega

Data: 2026-09-07. Branch `feat/iss-005-ingestao-mqtt-normalizacao`, criada a
partir de `origin/main` atualizada, base `f5c2ffc`. Implementação: `14306ca`
(`feat: normaliza leituras RFID com adapters MQTT explícitos`). A documentação
e este relatório compõem o commit seguinte, identificável pelo histórico da branch.

## Arquitetura e contrato entregue

O receptor Paho da ISS-001 mantém Settings, conexão, TLS/autenticação, QoS 1,
assinatura e modos local/cloud. Após preservar bytes e contexto, o parser
seleciona adapter e acrescenta `canonical_event` ao envelope JSONL existente.
O domínio recebe somente `event_id`, `epc`, `rssi`, `antenna`, `reader_id`,
`timestamp` UTC e metadata opcional. RSSI é número finito em dBm ou nulo quando
a unidade não está comprovada. Antena é inteiro positivo; EPC é texto não vazio.

`RFID_READER_ADAPTERS` mapeia reader_id para adapter e sobrepõe
`RFID_DEFAULT_ADAPTER` (`ez700`). Registry `ADAPTERS` permite extensão sem mudar
o consumidor. O adapter `simulator` lê `tag`, `port`, `signal` e `observed_at`;
EZ700 lê os campos da fixture já existente. Campos extras ficam em metadata.
Identidade vem do tópico e conflitos com qualquer identificador no payload
são rejeitados. Não há assinatura dupla nem alias legado: somente `easy/...`.

Timestamp aceita RFC3339 com timezone explícito e normaliza para UTC com seis
casas decimais. O perfil `EZ700_TIMESTAMP_FORMAT=epoch_ms` interpreta strings
de 13 dígitos apenas quando configurado. O simulador padrão e o marcador de
correlação de `verification` passaram a emitir RFC3339. RSSI EZ700 `-3880` é
preservado em metadata e não é convertido arbitrariamente.

`event_id` é SHA-256 versionado sobre tópico, adapter, formato de timestamp e
bytes originais. Reentrega dos mesmos bytes/contexto mantém ID; horários de
recepção e identificadores de transporte não entram no cálculo. Não é deduplicação
semântica: serializações diferentes diferem, e leituras idênticas podem compartilhar
ID. Essas limitações estão documentadas para ISS-006/ISS-014.

Inválidos mantêm evidência original, erros e evento canônico nulo. Limite
configurável de 65536 bytes por padrão evita parsing acima do limite, mas conserva
o conteúdo bruto. UTF-8 inválido fica em base64; overflow numérico/profundidade
excessiva são rejeitados e Unicode escapado não interrompe escrita. Logs incluem
tipo, leitor, adapter, resultado, motivo e ID sem registrar payload completo.
Falha de persistência continua fatal, conforme ISS-001.

Tipos, exemplos, algoritmo do ID, extensão, restrições e comandos completos:
[contrato canônico e adapters](../../rfid-normalization.md).

## Arquivos criados/alterados

| Arquivo | Mudança |
|---|---|
| `rfid_ingestion/normalization.py` | Novo: registry, adapters, validação canônica, timestamp, ID |
| `rfid_ingestion/config.py` | Opções de normalização no Settings existente |
| `rfid_ingestion/parsing.py` | Envelope enriquecido, tamanho, números finitos e profundidade |
| `rfid_ingestion/mqtt_client.py` | Encaminhamento de Settings e log estruturado após auditoria |
| `rfid_ingestion/persistence.py` | Escape Unicode seguro mantendo valores JSON |
| `rfid_ingestion/simulator.py` | `--format simulator` e relógio sintético RFC3339 |
| `rfid_ingestion/verification.py` | Marcador sintético RFC3339 compatível com a validação |
| `tests/test_normalization.py` | Novo: contrato, equivalência, erros, extensão e continuidade |
| `tests/test_integration.py` | Publicadores com adapters distintos/replay e assertivas canônicas |
| `tests/test_managed_mqtt.py` | Fixture com tópico correspondente e perfil epoch_ms explícito |
| `README.md` | Fase de software e referências ao contrato/relatório |
| `docs/mqtt-ingestion.md` | Configuração, payloads e comportamento atualizado |
| `docs/rfid-normalization.md` | Novo: especificação e reprodução |
| `docs/evidence/iss005/README.md` | Novo: este relatório |

Fixture física intacta. Nenhum artefato da ISS-002a foi alterado. Os arquivos
preexistentes não rastreados `pr-36-info.json` e `pr-36.patch` foram preservados
fora dos commits. Nenhum perfil privado, credencial ou certificado foi adicionado.

## Resultados executados

| Validação | Resultado efetivo |
|---|---|
| `python -m unittest discover -s tests -v`, Windows com MQTT ativado | 43 testes: 40 aprovados, 3 TLS com skip por OpenSSL ausente no PATH Windows |
| Mesmo comando, Ubuntu 24.04/WSL com OpenSSL | 43 testes: 41 aprovados, 2 integrações MQTT com skip explícito |
| União das execuções | Todos os 43 testes distintos passaram; nenhuma falha aberta |
| Integração anterior no Mosquitto real | 40 canônicos + 2 inválidos = 42 registros JSONL |
| Integração nova no Mosquitto real | 4 publicações: dois formatos simultâneos, campos relevantes equivalentes, dois reader_ids e dois event_ids estáveis no replay |
| Handshakes TLS em loopback Ubuntu | CA confiável aprovada; CA desconhecida e hostname incorreto rejeitados |
| Wrapper `bash tests/reader-connectivity/mqtt/smoke-test.sh` | Tentado; não executou broker por integração Docker WSL desabilitada; pendente/opcional neste ambiente |
| Alternativa ao wrapper | Mesmo Compose isolado via Docker Windows em loopback:18884 e suíte com MQTT ativado; aprovado |
| `bash -n` do smoke | Aprovado; script não alterado |
| `compileall`, `git diff --check`, `git diff --cached --check` | Aprovados |

Não foram 43 aprovações em cada sistema. Nenhum resultado é evidência de HiveMQ,
leitor físico, perda de leituras ou topologia de redes distintas. Broker/rede
temporários do Compose foram removidos ao terminar.

## Comandos de reprodução usados

PowerShell, com Docker Desktop ativo:

```powershell
$env:MQTT_BIND_ADDRESS='127.0.0.1'
$env:MQTT_LOCAL_PORT='18884'
docker compose -p rfid-iss005-smoke up -d
try {
    $env:RUN_MQTT_INTEGRATION='1'
    $env:TEST_MQTT_PORT='18884'
    & .venv/Scripts/python.exe -m unittest discover -s tests -v
} finally {
    docker compose -p rfid-iss005-smoke down
}
```

Ubuntu/WSL (Paho existente reutilizado; sem instalar dependências globais):

```bash
cd /mnt/c/Users/crowp/dev/rfid-hospital-mvp
PYTHONPATH=.venv/Lib/site-packages python3 -m unittest discover -s tests -v
bash -n tests/reader-connectivity/mqtt/smoke-test.sh
# Após disponibilizar Docker na distribuição:
PYTHONPATH=.venv/Lib/site-packages bash tests/reader-connectivity/mqtt/smoke-test.sh
```

## Pendências e revisão humana

**PENDENTE DE VALIDAÇÃO FÍSICA:** escala/unidade RSSI, semântica e precisão do
timestamp numérico, relógio do leitor e validação com EZ700 real. Suporte a
TLS/firmware, autenticação/ACL cloud e redes distintas continuam pertencendo às
validações externas já documentadas; não foram declarados aprovados aqui.

Antes do PR/merge, Thiego/Otávio devem revisar o contrato de RSSI nullable,
seleção explícita de epoch_ms e limite da identidade por bytes. Confirmar também
unicidade dos reader_ids no filtro assinado para configuração por leitor.
O wrapper shell integral permanece pendente até disponibilizar Docker no Ubuntu.

Código preparado para revisão. Revisão pela dupla ainda não realizada; portanto,
essa etapa da Definition of Done não foi declarada concluída. Sem push, merge,
fechamento de issue ou alteração de ACL/credenciais.
