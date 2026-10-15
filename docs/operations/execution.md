# Operação e configuração

Execute os comandos na raiz com o ambiente virtual ativado. Os perfis reais ficam em
`config/environments/` e não são versionados. O launcher usa `.env.local` ou
`.env.cloud` dessa pasta. Uma configuração explícita por `--env-file` continua aceita.
Os comandos da [página inicial](../../README.md) iniciam a demonstração completa.

## Instalação

Python 3.12, Node.js 22 e Docker Compose v2. No Windows use Docker Desktop com
backend WSL2 e execute Python no Windows para abrir a interface gráfica Flet.
No Ubuntu 24.04 use Docker Engine e um terminal gráfico; observadores podem usar tmux.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements/lab.txt
python -m pip install -r requirements/dev.txt
npm --prefix frontend ci
```

No PowerShell, ative com `.venv\Scripts\Activate.ps1`. Os demais comandos Python,
Docker e npm são equivalentes. Para copiar exemplos, use `cp` no Ubuntu ou
`Copy-Item` no PowerShell.

## Quatro modos

| Comando | Resultado |
|---|---|
| `python scripts/dev.py --teste 1` | API + interface + infraestrutura local + simulador visual |
| `python scripts/dev.py --teste 2` | API + interface + infraestrutura local + leitor físico |
| `python scripts/dev.py --teste 3` | API + interface + ingestor com broker/banco externos + leitor físico |
| `python scripts/dev.py --teste 4` | API + interface + ingestor com broker/banco externos + simulador visual |
| `python scripts/dev.py --sem-teste` | API + interface no perfil externo; infraestrutura já deve estar preparada |

`--sem-navegador`, `--api-port`, `--front-port` e `--env-file` ajustam a inicialização.
O launcher aguarda saúde dos serviços, aplica migrations e semeia a topologia.
No modo local pergunta sobre reaproveitamento dos dados. O reset remove volumes
somente após escolha explícita. O projeto externo nunca recebe reset de volumes.

## Perfis locais

```bash
cp config/environments/.env.local.example config/environments/.env.local
```

No modo local, o launcher deriva a URL de `POSTGRES_USER`, `POSTGRES_PASSWORD`,
`POSTGRES_DB` e `POSTGRES_PORT`; não utiliza uma URL externa exportada no shell.
Ao mudar essas chaves, ajuste também `DATABASE_URL`/`APP_DATABASE_URL` do arquivo
se executar os componentes individualmente. O administrador lê `DATABASE_URL`.

| Variável | Uso |
|---|---|
| `COMPOSE_PROJECT_NAME` | Isola os serviços e volumes do ensaio |
| `POSTGRES_PORT` | Porta publicada no host; padrão 5432 |
| `MQTT_LOCAL_PORT` | Porta publicada do Mosquitto; padrão 1883 |
| `MQTT_BIND_ADDRESS` | Endereço do broker no host; `0.0.0.0` permite o leitor na LAN |
| `MQTT_TOPIC` | Assinatura do ingestor; padrão `easy/dev/hupaa/+/+/readings` |
| `DATABASE_URL` | Migrations, API, seed e administração |
| `APP_DATABASE_URL` | Escrita do ingestor; no modo local é derivada pelo launcher |
| `EVENTS_FILE` | Auditoria local; padrão `data/raw_events.jsonl` |

O `name` padrão do Compose e o nome da imagem preservam a identidade legada dos
recursos locais. A mudança de nome do projeto/repositório não migra nem apaga volumes.

## Executar componentes separadamente

```bash
docker compose -f deploy/compose.yaml --env-file config/environments/.env.local --profile local up -d --build --wait
python -m api.criar_admin --env-file config/environments/.env.local --nome "Administrador" --email admin@hupaa.example
python -m uvicorn api.main:app --env-file config/environments/.env.local --host 127.0.0.1 --port 8010
# Outro terminal
npm --prefix frontend run dev
```

O Compose inicia banco, broker, migrations e ingestor. Não inclui API nem frontend.
O Vite encaminha as rotas de backend para `http://127.0.0.1:8010` por padrão; a
variável `RFID_API_URL` altera o destino. O frontend usa a mesma origem para cookies.
Se iniciar a infraestrutura sem o launcher, prepare os cadastros antes da ingestão:

```bash
# Ubuntu: exporta o perfil para os módulos que leem o ambiente do processo
set -a
source config/environments/.env.local
set +a
python -m tools.lab_launcher.seed
```

No Windows use preferencialmente o launcher, que carrega o arquivo sem `source`.
A autenticação usa cookie HttpOnly/SameSite=Strict, senha Argon2id e perfis de
consulta/administração. `python -m api.criar_admin --help` descreve a recuperação
administrativa. Não passe senhas na linha de comando.

## Leitor físico

Cadastre leitor, portas de antena, portal, lados A/B e zonas coerentes com o ensaio.
O leitor publica no broker acessível na rede existente; o notebook não cria hotspot.
Exemplo de tópico para o cadastro padrão: `easy/dev/hupaa/portal-01/reader-01/readings`.
O identificador no tópico deve corresponder a `reader_id`; o serial físico é separado.

```bash
python -m tools.lab_launcher start --env local --source physical --reader-id reader-01 --tag "3034000000000C40000000E8=Bomba de infusão 01"
```

O launcher lista EPCs vistos nas últimas 24 h e permite o cadastro nomeado.
Não presume configuração de firmware, escala de RSSI, alcance ou protocolo adicional.
Consulte o [payload observado e o tratamento do contador](../implementations/hotfix-ez700-contador-timestamp.md).

## Broker e banco externos

```bash
cp config/environments/.env.cloud.example config/environments/.env.cloud
cp config/environments/.env.cloud.reader-01.example config/environments/.env.cloud.reader-01
```

Preencha os arquivos localmente. O primeiro é usado para assinatura e banco; o
segundo é usado pelo simulador para publicação. `DATABASE_URL` deve permitir
migrations e `APP_DATABASE_URL` deve permitir ingestão. A assinatura MQTT pode
usar curingas; o publicador precisa de tópico exato com permissão de Publish.
CONNACK não comprova essa permissão: o publicador acompanha o PUBACK.

```bash
python -m tools.lab_launcher start --env managed --source synthetic --env-file config/environments/.env.cloud --publisher-env-file config/environments/.env.cloud.reader-01
```

TLS na porta 8883 é o padrão. `--mqtt-transport plain` é opção explícita de
laboratório e usa `MQTT_PLAIN_*`; não desabilite a validação de certificados.
Esses modos utilizam endpoints existentes, sem configurar hospedagem da aplicação.

## Parada e diagnóstico

```bash
python -m tools.lab_launcher stop --env local
python -m tools.lab_launcher stop --env managed
make -f scripts/Makefile status-local
make -f scripts/Makefile logs-local
```

Logs do lançador completo: `data/dev/api.log` e `data/dev/front.log`. Observadores
mostram MQTT, ingestor e banco. `GET /health` da API confirma vida do processo;
não certifica conectividade com o banco. O healthcheck do ingestor verifica MQTT
e consulta ao banco. Consulte [validações](validation.md) antes de preparar uma versão.
