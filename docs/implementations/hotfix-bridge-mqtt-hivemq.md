# Hotfix — bridge MQTT local para o HiveMQ Cloud

## Problema e importância para o MVP

O EZ700 (firmware `0.8.70.0`) não conecta com `mqtts`: fica em `Not connected`
tanto no cluster HiveMQ Cloud (8883) quanto no broker público
`broker.hivemq.com:8883`, enquanto broker, credenciais e ACLs foram validados
pelo Ubuntu (issue #42 do repositório de acompanhamento). O ensaio de
16/10/2026 repetiu o resultado: com o leitor em `mqtts://`, nenhuma leitura
chegou ao cluster.

O cluster HiveMQ Cloud aceita somente TLS (8883) e WebSocket com TLS (8884); a
porta 1883 está fechada. Assim, trocar `mqtts://` por `mqtt://` no leitor não
leva as leituras ao cluster, e o broker público sem TLS deixa as mensagens
visíveis a qualquer pessoa. Sem um caminho do leitor até o broker gerenciado, o
ensaio com broker e banco externos não pode ser feito com o leitor físico.

## O que foi feito

Novo transporte `bridge` no launcher (`--mqtt-transport bridge`, opção 3 do
menu de transporte), somente para o leitor físico:

```text
EZ700 ──mqtt 1883, rede local──> mqtt-bridge (Mosquitto no notebook)
      ──mqtts 8883, credencial do leitor──> HiveMQ Cloud ──> ingestor-managed ──> banco externo
```

- `deploy/compose.yaml` ganhou o serviço `mqtt-bridge` no perfil `managed`,
  publicado em `MQTT_BIND_ADDRESS:MQTT_LOCAL_PORT` (padrão `0.0.0.0:1883`). Ele
  só sobe quando o launcher pede; o ingestor não depende dele.
- `docker/mosquitto-bridge.sh` gera a configuração dentro do contêiner a partir
  de variáveis `BRIDGE_*`; a senha não é gravada no repositório nem no host.
- `tools/lab_launcher/bridge.py` lê a credencial de publicação de
  `config/environments/.env.cloud.<reader-id>` (ou `--publisher-env-file`),
  exige que seja diferente da credencial do ingestor e que o tópico seja
  exatamente o do leitor, e espera a bridge informar que conectou.
- O ingestor continua no HiveMQ Cloud com TLS, como no transporte `tls`.

Decisões impostas pelo HiveMQ Cloud:

- Só o tópico `easy/dev/hupaa/<portal>/<leitor>/readings` é repassado. A ACL da
  credencial do leitor não permite publicar no `heartbeat`, e o HiveMQ derruba a
  conexão nesse caso (`Not authorized`, verificado em 16/10/2026). O heartbeat e
  o tópico de comando ficam apenas no broker local.
- `try_private false`: o cluster não reconhece o modo bridge privado do
  Mosquitto.
- Notificações de estado só no broker local
  (`$SYS/broker/connection/easy-bridge-<leitor>/state`, `1` = conectada), para
  não publicar fora da ACL.

O listener local continua anônimo e sem TLS, como o Mosquitto de
desenvolvimento: aceitável somente na rede controlada do laboratório. O trecho
que sai para a internet usa TLS com validação de certificado.

## Como usar

```bash
python -m tools.lab_launcher stop --env local      # libera a porta 1883
python -m tools.lab_launcher start --env managed --source physical --mqtt-transport bridge
```

O launcher mostra a URL a configurar no leitor:

| Campo do EZ700 | Valor |
|---|---|
| URL | `mqtt://<IP do notebook>` |
| Port | `1883` |
| Client ID | `reader-01` |
| Username / Password | vazios |
| Inventory's topic | `easy/dev/hupaa/portal-01/reader-01/readings` |

Para conferir a bridge:

```bash
docker exec rfid-hospital-managed-mqtt-bridge-1 \
  mosquitto_sub -h 127.0.0.1 -t '$SYS/broker/connection/#' -v -C 1 -W 3
```

## Validação

- `python -m ruff check --config config/ruff.toml --select E4,E7,E9,F,I .`
- `python -m pytest -q` com `TEST_DATABASE_URL` em PostgreSQL descartável:
  1370 testes aprovados.
- Testes novos: escolha do transporte `bridge`, credencial e tópico da bridge,
  recusa no simulador e serviço `mqtt-bridge` no perfil `managed`.
- Em 16/10/2026, a bridge conectou ao cluster com a credencial do `reader-01`
  (estado `1`). A chegada de leituras físicas do EZ700 por esse caminho permanece
  **PENDENTE DE VALIDAÇÃO FÍSICA**.
