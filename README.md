# RFID Hospital MVP

MVP para rastreabilidade aproximada, por zonas, de equipamentos hospitalares do HUPAA/UFAL utilizando RFID UHF passivo. A posição de um ativo será inferida principalmente por sua última passagem confirmada em uma zona, e não por posicionamento contínuo em ambientes internos.

## Fase atual

A Prova de Conceito foi concluída e a camada de comunicação do MVP já foi validada fisicamente com dois leitores Identix EZ700.

O notebook funciona como servidor local, executando:

- Broker MQTT Mosquitto.
- Serviço de ingestão em Python.
- Persistência inicial dos eventos em JSON Lines.

O notebook não cria obrigatoriamente uma rede Wi-Fi. Ele precisa estar conectado a uma rede pela qual os leitores consigam alcançar seu endereço IP e a porta MQTT.

A comunicação pela rede cabeada foi validada com dois leitores publicando simultaneamente:

```text
EZ700 -> rede local -> Mosquitto no notebook -> ingestor Python -> data/raw_events.jsonl
```

A rede poderá ser cabeada, Wi-Fi ou uma combinação das duas, desde que exista comunicação IP entre os leitores e o servidor. O funcionamento por Wi-Fi ainda precisa ser validado em uma rede estável.

## Como o servidor funciona

O servidor possui dois componentes principais: o Mosquitto e o ingestor Python.

### Mosquitto

O Mosquitto funciona como broker MQTT e escuta, no ambiente de desenvolvimento, a porta TCP `1883`.

Os leitores EZ700 conectam-se ao endereço IP do notebook e publicam suas leituras em tópicos individuais:

```text
rfid/<reader-id>/tags
```

Exemplos:

```text
rfid/EZ700-82-8A-54/tags
rfid/EZ700-82-89-14/tags
```

O Mosquitto recebe as mensagens e as distribui para os serviços inscritos nesses tópicos.

O broker é responsável pelo transporte das mensagens. Ele não interpreta o EPC, não calcula a localização dos equipamentos e não funciona como banco de dados definitivo da aplicação.

### Ingestor Python

O módulo `rfid_ingestion` conecta-se ao Mosquitto e se inscreve no padrão:

```text
rfid/+/tags
```

O caractere `+` permite receber eventos de diferentes leitores utilizando um único serviço de ingestão.

Para cada mensagem recebida, o ingestor:

1. Identifica o leitor pelo tópico MQTT.
2. Preserva o payload original.
3. Converte o payload para JSON.
4. Adiciona o horário de recebimento no servidor.
5. Registra informações como tópico, QoS e retain.
6. Preserva possíveis erros de conversão.
7. Anexa o evento ao arquivo `data/raw_events.jsonl`.

Exemplo simplificado de evento recebido:

```json
{
  "received_at_utc": "2026-08-20T15:42:17.301Z",
  "topic": "rfid/EZ700-82-8A-54/tags",
  "qos": 1,
  "retain": false,
  "payload_json": {
    "epc": "3034000000000C4000000072",
    "rssi": -6350,
    "antenna": 1,
    "timestamp": "1821775"
  },
  "parse_error": null
}
```

O formato real de publicação do EZ700 foi validado fisicamente. O receptor preserva o payload original e aceita campos adicionais para facilitar futuras alterações de configuração ou firmware.

## Papel do ingestor no software

O ingestor não é apenas um componente temporário de teste. Ele representa a camada de entrada dos dados RFID e deverá permanecer como parte fundamental do software.

Atualmente, ele recebe e preserva os eventos brutos em JSONL. Durante a evolução do projeto, poderá ser ampliado para:

- Validar a estrutura das mensagens.
- Identificar o equipamento associado ao EPC.
- Identificar a zona associada ao leitor.
- Tratar leituras repetidas.
- Comparar intensidade de sinal.
- Confirmar mudanças entre zonas.
- Registrar o estado dos leitores por heartbeat.
- Salvar leituras processadas em um banco de dados.
- Alimentar o backend e o dashboard em tempo real.

A evolução esperada é:

```text
EZ700
  -> Mosquitto
  -> ingestor RFID
  -> validação e processamento
  -> banco de dados
  -> backend/API
  -> dashboard em tempo real
```

Os eventos brutos em JSONL poderão continuar sendo armazenados para auditoria, testes, reprodução de sessões e reprocessamento com versões futuras dos algoritmos.

## Identificação dos leitores

Cada leitor deve possuir um Client ID e tópicos MQTT exclusivos.

| Leitor | Client ID | Tópico de inventário |
|---|---|---|
| Leitor 1 | `EZ700-82-8A-54` | `rfid/EZ700-82-8A-54/tags` |
| Leitor 2 | `EZ700-82-89-14` | `rfid/EZ700-82-89-14/tags` |

A identificação do leitor é obtida pelo tópico MQTT. Isso permite que vários leitores publiquem simultaneamente no mesmo broker sem misturar a origem das leituras.

## Execução rápida

No Ubuntu 24.04, a partir da raiz do repositório:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
docker compose up -d
python -m rfid_ingestion
```

Em outro terminal, com o mesmo ambiente virtual ativo, é possível executar o simulador:

```bash
source .venv/bin/activate
python -m rfid_ingestion.simulator \
  --reader-id EZ700-SIM-01 \
  --count 3 \
  --interval 1
```

Os eventos são anexados ao arquivo:

```text
data/raw_events.jsonl
```

Para visualizar diretamente as mensagens MQTT:

```bash
mosquitto_sub \
  -h 127.0.0.1 \
  -p 1883 \
  -t 'rfid/+/tags' \
  -v
```

Consulte também:

- [Guia completo de ingestão MQTT](docs/mqtt-ingestion.md)
- [Roteiro dos testes de rede](docs/experiments/mqtt-network-validation.md)

## Validações realizadas

Até o momento, foram validados:

- Comunicação real do EZ700 por MQTT.
- Formato JSON publicado pelo leitor.
- Leitor conectado à rede cabeada por DHCP.
- Mosquitto acessível pela porta `1883`.
- Recebimento de eventos por `mosquitto_sub`.
- Persistência dos eventos pelo ingestor.
- Dois leitores publicando simultaneamente.
- Separação dos leitores por Client ID e tópico.
- Simulação de movimentação de uma tag entre duas zonas.
- Armazenamento das coletas em sessões JSONL.

## Validações pendentes

Ainda precisam ser realizados:

- Comunicação com todos os dispositivos no mesmo Wi-Fi.
- Leitores no Wi-Fi e servidor na rede cabeada.
- Comunicação entre sub-redes diferentes.
- Validação das regras de rede e firewall do hospital.
- Testes com o dashboard em tempo real.
- Testes prolongados de estabilidade e reconexão.
- Integração com banco de dados e backend.
- Tratamento definitivo de leituras repetidas.
- Inferência de mudança entre zonas.
- Configuração de autenticação e segurança para produção.

O teste pelo Wi-Fi do Instituto de Computação não foi concluído porque a rede apresentou falha na obtenção de endereço IP. O hotspot móvel também não pôde ser utilizado devido à ausência de sinal adequado no laboratório.

## Considerações para implantação

No ambiente definitivo, o servidor deverá possuir um endereço estável, preferencialmente por IP fixo ou reserva DHCP.

Caso o endereço IP do servidor seja alterado, será necessário atualizar a URL do broker MQTT na configuração de cada leitor:

```text
mqtt://IP_DO_SERVIDOR
```

Também deverão ser avaliados:

- Autenticação MQTT.
- Controle de acesso aos tópicos.
- Regras de firewall.
- Segmentação da rede.
- Inicialização automática dos serviços.
- Persistência e backup.
- Monitoramento dos leitores.
- Criptografia, caso suportada pelo firmware e pela infraestrutura.

## Escopo atual

Esta etapa contém:

- Broker MQTT Mosquitto.
- Serviço permanente de ingestão RFID.
- Simulador de leitores.
- Persistência bruta em JSONL.
- Separação de múltiplos leitores por tópico.
- Testes automatizados.
- Roteiros de validação de rede.
- Captura de sessões para reprodução e análise.

Continuam em desenvolvimento:

- Banco de dados da aplicação.
- Backend e API.
- Dashboard e frontend.
- CRUD de equipamentos e leitores.
- Lógica definitiva de localização por zonas.
- Deduplicação e agregação.
- Implantação no ambiente hospitalar.
- Configuração de produção e segurança.

## Materiais do projeto

Documentos, registros, vídeos e demais materiais relacionados ao projeto estão disponíveis no Google Drive:

[Google Drive — RFID Hospital MVP](https://drive.google.com/drive/folders/1AYqcT6jRI6UQNMan_DnyVXhEiNwMNgse?hl=pt-br)