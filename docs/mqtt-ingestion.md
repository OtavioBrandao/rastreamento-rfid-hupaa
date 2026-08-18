# Ingestão MQTT local

## Finalidade

Esta camada recebe eventos RFID por MQTT e os grava localmente em JSON Lines. Ela permite validar rede, tópicos e payloads antes de implementar banco de dados, regras de portal ou dashboard.

```text
EZ700 -> Wi-Fi local -> Mosquitto no notebook -> receptor Python -> JSONL
```

Notebook e leitores devem estar na mesma rede. O notebook não funciona como hotspot e nenhum componente deste repositório altera configurações de rede do sistema operacional.

## Componentes

- `compose.yaml`: Mosquitto local em contêiner.
- `mosquitto/mosquitto.dev.conf`: listener de desenvolvimento na porta 1883.
- `rfid_ingestion/`: configuração, parsing, persistência, logging, cliente e simulador.
- `data/raw_events.jsonl`: saída padrão em execução; ignorada pelo Git.
- `tests/fixtures/identix/tag-read.json`: exemplo baseado no formato documentado pela Identix.
- `tests/reader-connectivity/mqtt/smoke-test.sh`: integração local opcional com Docker.

## Pré-requisitos no Ubuntu 24.04

- Python 3.10 ou mais recente, com `venv` e `pip`.
- Docker com o plugin Compose para a opção recomendada de broker; ou Mosquitto instalado nativamente.
- Acesso local à porta TCP 1883.

Instalação da aplicação em ambiente virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

O único pacote Python de execução é o cliente Eclipse Paho MQTT 2.x. A aplicação usa a versão 2 da API de callbacks.

## Configuração

Todas as opções do receptor vêm do ambiente:

| Variável | Padrão | Finalidade |
|---|---|---|
| `MQTT_HOST` | `127.0.0.1` | Endereço do broker |
| `MQTT_PORT` | `1883` | Porta TCP do broker |
| `MQTT_TOPIC` | `rfid/+/tags` | Assinatura do receptor |
| `MQTT_USERNAME` | vazio | Usuário opcional |
| `MQTT_PASSWORD` | vazio | Senha opcional |
| `MQTT_CLIENT_ID` | `rfid-mvp-receiver` | Identificador MQTT do receptor |
| `MQTT_QOS` | `1` | QoS da assinatura: 0, 1 ou 2 |
| `EVENTS_FILE` | `data/raw_events.jsonl` | Destino JSONL |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` ou `CRITICAL` |

O tópico pode ser alterado sem mudar código. Para descoberta inicial e controlada do leitor, `MQTT_TOPIC='#'` captura todos os tópicos; não use essa assinatura ampla como padrão operacional.

O arquivo `.env.example` não contém credenciais. A aplicação lê o ambiente, não o arquivo diretamente. Se quiser usar um `.env` local, revise-o e carregue-o no shell:

```bash
cp .env.example .env
set -a
source .env
set +a
```

O `.env` é ignorado pelo Git. Nunca registre credenciais reais, logs com segredos ou configurações exportadas do leitor.

## Broker com Docker Compose

Na raiz do repositório:

```bash
docker compose config
docker compose up -d
docker compose logs -f mosquitto
```

O listener usa `0.0.0.0:1883`, portanto aceita conexões de outras máquinas da rede local. O mapeamento não deve ser publicado em roteador, encaminhado para a internet ou usado em rede não confiável.

Para encerrar:

```bash
docker compose down
```

## Alternativa nativa no Ubuntu

Instale manualmente os pacotes, se autorizado na máquina:

```bash
sudo apt update
sudo apt install mosquitto mosquitto-clients
```

Uma forma isolada de usar a configuração do repositório é interromper temporariamente o serviço instalado, executar o broker no terminal e restaurar o estado anterior ao final:

```bash
systemctl is-active mosquitto
sudo systemctl stop mosquitto
mosquitto -c mosquitto/mosquitto.dev.conf -v
```

Encerre o processo com `Ctrl+C`. Reinicie o serviço somente se ele estava ativo antes do teste:

```bash
sudo systemctl start mosquitto
```

Não execute uma segunda instância se a porta 1883 já estiver ocupada.

## Executar o receptor

Com o ambiente virtual ativo e o broker em execução:

```bash
python -m rfid_ingestion
```

O receptor faz nova assinatura após reconexões, registra mensagens válidas ou inválidas e continua ativo quando um payload não é JSON. Encerre de forma limpa com `Ctrl+C`.

Para observar o arquivo em outro terminal:

```bash
tail -f data/raw_events.jsonl
```

Cada linha contém:

- `received_at_utc`: horário UTC de recebimento pelo notebook;
- `topic`, `qos` e `retain`: metadados MQTT;
- `payload_original`: texto UTF-8 recebido;
- `payload_encoding`: `utf-8` ou `base64` para bytes inválidos;
- `payload_json`: valor JSON interpretado, inclusive campos adicionais;
- `parse_error`: descrição sanitizada quando o parsing falha.

Payloads que não são UTF-8 ficam codificados em base64 para preservar exatamente os bytes originais.

## Formato provisório do EZ700

O exemplo atualmente usado é:

```json
{
  "epc": "E2801190A502006016C32F62",
  "tid": "E280119020004F62B6190300",
  "timestamp": "1632759395291",
  "rssi": -3880,
  "phase": 49,
  "channel": 906250,
  "antenna": 1,
  "readerid": "EZ700-PORTAL-01"
}
```

O receptor não exige esses campos e preserva propriedades adicionais. Tópico, nomes, unidades, tipos e comportamento real ainda precisam ser confirmados no firmware e no teste físico do EZ700.

## Executar o simulador

Publicar uma mensagem com tópico derivado do identificador:

```bash
python -m rfid_ingestion.simulator --reader-id EZ700-SIM-01 --antenna 1
```

Publicar cinco mensagens a cada dois segundos em um tópico explícito:

```bash
python -m rfid_ingestion.simulator \
  --reader-id EZ700-PORTAL-02 \
  --antenna 2 \
  --topic rfid/portal-02/tags \
  --count 5 \
  --interval 2
```

O simulador usa `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME` e `MQTT_PASSWORD` do ambiente. Senhas não são aceitas como argumento de linha de comando para evitar o histórico do shell.

## IP do notebook e porta MQTT

Identifique interfaces e endereços sem presumir nomes como `wlan0`:

```bash
nmcli -f DEVICE,TYPE,STATE,CONNECTION device status
ip -4 -brief address show up
```

Use no leitor o IPv4 da interface conectada à mesma rede Wi-Fi. Endereços de Docker, loopback e outras redes não devem ser usados pelo EZ700.

Confirme no notebook que o broker escuta em todas as interfaces:

```bash
ss -ltnp | grep ':1883'
```

De outro computador na mesma rede, teste a porta e publique uma mensagem:

```bash
nc -vz IP_DO_NOTEBOOK 1883
mosquitto_pub -h IP_DO_NOTEBOOK -p 1883 \
  -t rfid/teste-remoto/tags \
  -m '{"readerid":"teste-remoto","epc":"E280TESTE"}'
```

Se o UFW estiver ativo, prefira liberar temporariamente apenas a sub-rede local aprovada, conforme orientação da TI, e remova a regra após o teste. Não abra a porta 1883 para a internet.

## Teste automatizado e smoke test

Os testes unitários não exigem broker:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

Com Docker e dependências Python disponíveis, execute a integração local:

```bash
./tests/reader-connectivity/mqtt/smoke-test.sh
```

O script inicia um projeto Compose isolado, aguarda o receptor assinar, publica um evento, confirma o JSONL temporário e encerra os processos e o contêiner.

## Roteiro das redes

### Hotspot do celular

- Preferir 2,4 GHz e conectar celular, notebook e EZ700 à mesma rede.
- Dados móveis não são necessários para tráfego local.
- Usar o IP Wi-Fi do notebook como broker.
- Verificar isolamento entre clientes, alcance, estabilidade e múltiplos leitores.

### Wi-Fi institucional

- Verificar autenticação suportada pelo EZ700 e portal de login.
- Testar isolamento entre clientes, firewall e porta 1883.
- Observar mudanças do IP do notebook.
- Solicitar apoio da TI quando VLAN, regra de entrada ou reserva de endereço forem necessárias.

O registro completo e os critérios de aceitação estão em [`experiments/mqtt-network-validation.md`](experiments/mqtt-network-validation.md).

## Segurança e limitações

A configuração `mosquitto.dev.conf` usa acesso anônimo e MQTT sem TLS exclusivamente para o primeiro teste em rede local controlada. Ela não fornece confidencialidade, autenticação ou autorização e não deve ser usada em produção, em Wi-Fi público ou com encaminhamento de porta.

Antes de uma implantação real serão necessários, no mínimo, autenticação individual, ACL de tópicos, TLS, gestão de certificados/segredos, política de retenção, monitoramento e análise da rede hospitalar. Também permanecem pendentes a validação de MQTTS no EZ700, comportamento offline, reconexão, perda de eventos e carga simultânea.

## Referências oficiais

- [Eclipse Paho MQTT Python](https://eclipse.dev/paho/files/paho.mqtt.python/html/)
- [Configuração do Mosquitto](https://mosquitto.org/man/mosquitto-conf-5.html)
- [Métodos de autenticação do Mosquitto](https://mosquitto.org/documentation/authentication-methods/)
