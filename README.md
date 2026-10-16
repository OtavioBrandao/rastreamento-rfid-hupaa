# Rastreamento RFID HUPAA

MVP experimental para rastrear equipamentos móveis do **Hospital Universitário Professor Alberto Antunes (HUPAA/UFAL)** com RFID UHF passivo. O software registra leituras, reconhece passagens entre zonas e apresenta a última zona confirmada de cada equipamento, seu histórico e a atividade das antenas.

O objetivo é reduzir o tempo de procura por equipamentos e apoiar a gestão do parque hospitalar. A planta representa zonas e portais; os marcadores têm posição ilustrativa. Uma leitura recente indica presença na antena. A localização muda após uma passagem com direção confirmada ou uma correção manual auditada.

## Demonstração do funcionamento

Capturas reais da aplicação com **dados sintéticos**, em um ambiente local
isolado. O publicador do simulador percorreu MQTT → ingestor → PostgreSQL →
passagem/direção → histórico/última zona → API → interface.

![Dashboard com quatro equipamentos fictícios, três passagens confirmadas e leituras recentes](docs/assets/screenshots/dashboard-simulacao.jpg)

| Planta EASY e equipamentos por zona | Leituras por tag e antena |
|---|---|
| ![Mapa EASY com uma tag na Zona A e duas na Zona B](docs/assets/screenshots/mapa-easy-simulacao.jpg) | ![Contagem de leituras por equipamento e por antena](docs/assets/screenshots/leituras-simulacao.jpg) |

O ensaio confirmou duas passagens A→B e uma B→A. Um quarto equipamento ficou
sem leitura, permitindo comparar presença, zona confirmada e ausência de detecção.
[Veja a galeria completa, o histórico e a evidência do pipeline](docs/experiments/galeria-pipeline.md).
As imagens não representam ensaio RF nem dados de operação do hospital.

### Planta de referência do HU

![Planta esquemática do segundo pavimento do HUPAA com três zonas provisórias](docs/assets/screenshots/mapa-hupaa-referencia.jpg)

A visualização do HU usa a planta de referência do segundo pavimento e três
zonas provisórias. Nomes, limites e posições de hardware serão conferidos com
a equipe do hospital. A captura mostra o esquema e seus vínculos de cadastro;
os equipamentos do ensaio EASY continuam em suas próprias zonas.
[Como mapear leitores, antenas, portais e cadastrar as tags no HU](docs/operations/implantacao-hupaa.md).

## Executar o projeto

Requisitos: **Python 3.12**, **Node.js 22**, Docker com Compose v2 e ambiente gráfico para o simulador Flet. O desenvolvimento contempla Ubuntu 24.04 e Windows 11 com Docker Desktop/WSL2. Execute os comandos na raiz do repositório.

```bash
python -m venv .venv
# Ubuntu 24.04
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements/lab.txt
npm --prefix frontend ci
```

### Configurar os arquivos de ambiente

Os arquivos `.example` são modelos versionados. Copie os perfis necessários e
edite **as cópias**, mantendo credenciais fora do Git. No Ubuntu:

```bash
cp config/environments/.env.local.example config/environments/.env.local
# Somente para broker/banco externos (opções 3 e 4)
cp config/environments/.env.cloud.example config/environments/.env.cloud
# Somente para o simulador externo (opção 4)
cp config/environments/.env.cloud.reader-01.example config/environments/.env.cloud.reader-01
```

No PowerShell, substitua `cp` por `Copy-Item`. Não sobrescreva um perfil já
preenchido; abra-o e ajuste apenas os campos necessários.

| Perfil | O que configurar |
|---|---|
| `.env.local` | Os padrões atendem ao laboratório local. Ajuste `POSTGRES_PORT` e `MQTT_LOCAL_PORT` se as portas estiverem ocupadas. Para leitor físico, permita acesso à porta do broker pela LAN. |
| `.env.cloud` | `MQTT_HOST` sem `mqtts://` nem porta, usuário/senha de **assinatura**, `MQTT_CLIENT_ID` único, `MQTT_TOPIC`, `DATABASE_URL` e `APP_DATABASE_URL`. Mantenha TLS habilitado. |
| `.env.cloud.reader-01` | Mesmo broker, credencial separada com permissão de **publicação** e tópico exato autorizado para o leitor simulado. |

Exemplo de campos externos, com valores fictícios:

```dotenv
MQTT_HOST=seu-cluster.hivemq.cloud
MQTT_PORT=8883
MQTT_TLS_ENABLED=true
MQTT_USERNAME=usuario-do-ingestor
MQTT_PASSWORD=preencha-apenas-no-arquivo-local
MQTT_CLIENT_ID=hupaa-ingestor-seu-identificador
MQTT_TOPIC=easy/dev/hupaa/+/+/readings
DATABASE_URL=postgresql+psycopg2://usuario:senha@servidor/banco?sslmode=require
APP_DATABASE_URL=postgresql+psycopg2://usuario:senha@servidor-pooler/banco?sslmode=require
```

`DATABASE_URL` atende API, migrations e cadastros iniciais; `APP_DATABASE_URL`
atende o ingestor. Devem apontar para o **mesmo banco lógico**. Use o endpoint
direto para migrations quando o provedor exigir; o ingestor pode usar o pooler.
Codifique caracteres especiais da senha na URL (`@` vira `%40`, por exemplo).
Não copie o exemplo fictício sobre um perfil local funcional.

No modo local o launcher deriva as URLs dos campos `POSTGRES_*`. Se executar
API/administração separadamente após alterar porta, usuário, senha ou banco,
atualize também as URLs no perfil. `TEST_DATABASE_URL` é exclusiva de um banco
descartável: os testes apagam dados. Não use o banco da demonstração para a suíte.
O [guia de configuração](docs/operations/execution.md) detalha portas, transporte,
permissões MQTT e execução por componente.

### Modo de simulação

```bash
python scripts/dev.py --teste 1
```

O launcher prepara PostgreSQL e Mosquitto locais, aplica migrations, cadastra a topologia EASY e inicia o ingestor. A API e o frontend abrem junto com a janela do simulador. Defina os nomes dos equipamentos e arraste os itens entre as antenas A e B. Saia do alcance de uma antena e entre no da outra dentro da janela de passagem para observar a mudança de zona.

O perfil `config/environments/.env.local` é criado a partir do exemplo quando ainda não existe. Para acessar as telas, crie o administrador inicial em outro terminal **depois de o launcher concluir as migrations**:

```bash
python -m api.criar_admin --env-file config/environments/.env.local --nome "Administrador" --email admin@hupaa.example
```

A senha é solicitada no terminal. Frontend: [localhost:5173](http://localhost:5173/). API/OpenAPI: [127.0.0.1:8010/docs](http://127.0.0.1:8010/docs). `Ctrl+C` encerra a sessão; a exclusão de volumes locais exige escolha explícita.

### Modo com dados do leitor

```bash
python scripts/dev.py --teste 2
```

Conecte o leitor e o notebook a uma rede existente com comunicação IP permitida. Configure no leitor o endereço do broker no notebook, a porta MQTT e o tópico autorizado. O notebook atua como broker/receptor; não é configurado como hotspot. O menu solicita as tags e os nomes dos equipamentos e usa o identificador lógico `reader-01` por padrão.

Para um leitor com identificador diferente, use o launcher diretamente e informe o identificador presente no tópico:

```bash
python -m tools.lab_launcher start --env local --source physical --reader-id reader-01
```

Esse comando inicia a infraestrutura e os observadores. Para executar API e frontend separadamente, siga o [guia de operação](docs/operations/execution.md). O adapter EZ700 aceita o payload observado nos ensaios; novos firmwares, protocolos, contadores e unidades de RSSI precisam de validação física.

### Modos disponíveis

Sem argumentos, `python scripts/dev.py` apresenta o menu completo:

| Opção | Fonte de dados | Broker e banco | Perfil |
|---|---|---|---|
| 1 | Simulador visual | Mosquitto + PostgreSQL locais | `config/environments/.env.local` |
| 2 | Leitor físico | Mosquitto + PostgreSQL locais | `config/environments/.env.local` |
| 3 | Leitor físico | MQTT e PostgreSQL externos | `config/environments/.env.cloud` |
| 4 | Simulador visual | MQTT e PostgreSQL externos | `config/environments/.env.cloud` + perfil do publicador |

Para 3 e 4, copie e preencha o exemplo correspondente em `config/environments/`. A opção 4 exige credencial de publicação separada da assinatura do ingestor. TLS é o padrão externo; MQTT sem TLS exige escolha explícita de laboratório. Como o EZ700 não conecta com `mqtts`, a opção 3 aceita `--mqtt-transport bridge`: o leitor publica sem TLS no notebook e uma [bridge](docs/implementations/hotfix-bridge-mqtt-hivemq.md) repassa as leituras ao HiveMQ Cloud com TLS. `python scripts/dev.py --sem-teste` executa apenas API e frontend no banco externo já preparado.

Os perfis reais são ignorados pelo Git. Exemplos versionados não devem receber credenciais. [Configuração, portas e comandos por componente](docs/operations/execution.md).

## Arquitetura com leitores RFID

```mermaid
flowchart LR
    TAG[Tags UHF passivas] -. RF .-> ANT[Antenas A e B]
    ANT --- READER[Leitores RFID Identix EZ700]
    READER -->|MQTT QoS 1| BROKER[Broker Mosquitto local ou MQTT externo]
    BROKER --> ING[Ingestor Python / Paho]
    ING --> RAW[(PostgreSQL: leituras brutas)]
    READER -. Heartbeat opcional validado .-> BROKER
    ING --> STATUS[Último contato / estado dos leitores e portais]
    STATUS --> RAW
    ING --> LOG[Auditoria JSONL local]
    RAW --> ACK[Persistência confirmada / PUBACK]
    ACK --> BROKER
    ING --> DEB[Debounce por EPC e antena]
    DEB --> PASS[Passagem e direção A/B]
    PASS --> LOC[Histórico e última zona]
    LOC --> RAW
    RAW --> API[FastAPI / autenticação / permissões]
    API --> UI[React / dashboard / mapas / leituras]
```

O tópico identifica o leitor; o cadastro resolve sua porta em uma antena ativa. Mapeamentos temporais definem lado, portal e zona. A consolidação de leituras alimenta o detector de passagens, que rejeita situações de sobreposição e respeita um período refratário. Apenas direção confirmada alimenta a movimentação automática. Histórico e projeção de localização são atualizados na mesma transação, sem fazer a zona regredir por eventos atrasados.

Leitores e notebook usam a rede disponível. Mosquitto e PostgreSQL podem operar localmente; os modos externos substituem esses serviços por endpoints configurados. O funcionamento completo em campo depende da topologia real, da rede institucional e da calibração das antenas. [Arquitetura detalhada com hardware](docs/architecture/system-overview.md#arquitetura-com-leitores).

### Mapeamento para o setor piloto do HU

O cadastro segue **andar → setor → zona**. As zonas ligam-se ao desenho por
`referencia_planta` (`zona-1`, `zona-2`, `zona-3`). Cada leitor recebe um
`reader_id` próprio; cada porta é cadastrada como antena e associada ao portal,
lado A/B e zona adjacente. Um portal pode reunir antenas de leitores diferentes.

```mermaid
flowchart LR
    R[Leitor / reader_id] --> A[Antena / porta]
    A --> P[Portal / lado A ou B / zona]
    T[EPC da etiqueta] --> E[Equipamento cadastrado]
    P --> PASS[Passagem com direção confirmada]
    E --> PASS
    PASS --> H[Histórico e última zona no mapa do HU]
```

Após cadastrar o tipo e o equipamento com seu identificador interno, associe o
EPC efetivamente lido da etiqueta. Cadastrar uma tag não define sua localização:
a zona é confirmada pelo pipeline de passagem ou por correção manual auditada.
Os ícones da planta usam posições configuradas, sem cálculo de coordenadas por RSSI.
[Guia técnico: cadastros, endpoints, mapeamentos, rede e conferência em campo](docs/operations/implantacao-hupaa.md).

## Arquitetura com simulador

```mermaid
flowchart LR
    USER[Operador arrasta equipamentos] --> FLET[Simulador visual Flet / planta EASY]
    FLET --> PUB[Publicador MQTT / EPCs sintéticos]
    PUB --> BROKER[Mosquitto local ou MQTT externo]
    BROKER --> ING[Mesmo ingestor e adapter do ensaio]
    ING --> DB[(PostgreSQL)]
    ING --> PIPE[Debounce / passagem / direção]
    PIPE --> PROJ[Histórico / última zona]
    PROJ --> DB
    DB --> API[FastAPI]
    API --> UI[React / mapa EASY / leituras]
```

O simulador gera tags de 96 bits, cadastra os equipamentos e publica leituras conforme a posição ilustrativa dos itens. A partir do broker, percorre o mesmo pipeline usado no ensaio com leitor. Alcance, RSSI e período de leitura do simulador são parâmetros de demonstração, sem equivalência metrológica com o hardware. [Fluxo e limites do simulador](docs/architecture/system-overview.md#arquitetura-com-simulador).

## Inventário e monitoramento

O inventário e os mapas abrem com os cadastros ativos. No dashboard, marque
**Mostrar cadastros inativos** para consultar os anteriores. Inativar um cadastro
preserva EPC, leituras e histórico. [Detalhes do recorte operacional](docs/implementations/inventario-cadastros-inativos.md).

### Status dos leitores e portais

A tela **Status dos leitores**, disponível aos perfis operacional e administrador,
mostra online, degradado, offline e nunca conectado, com último contato e motivo.
Portais agregam os componentes ativos e indicam falhas parciais. A API recalcula
o timeout em cada consulta, inclusive se o ingestor parar.

Configure os mesmos limites nos processos da API e do ingestor:

```dotenv
RFID_READER_DEGRADED_SECONDS=30
RFID_READER_OFFLINE_SECONDS=90
MQTT_HEARTBEAT_TOPIC=
```

Uma leitura válida não retida renova o contato. Para acompanhar um leitor sem
tags, habilite um tópico de heartbeat e uma fonte compatível, com ACL própria.
Esse contrato é opcional do software e precisa ser validado no leitor físico.
[Configuração e ensaio de heartbeat independente](docs/implementations/iss-024-status-leitores.md#configuração).

![Painel com contatos por leitura e heartbeat independente, com dados sintéticos](docs/assets/screenshots/status-leitores-simulacao.jpg)

## Tecnologias e organização

| Camada | Tecnologia e responsabilidade |
|---|---|
| Interface | React 19, TypeScript, Vite; atualização periódica de consultas |
| API | FastAPI, Pydantic, Uvicorn; cadastros, busca, autenticação, auditoria |
| Ingestão | Python 3.12, Paho MQTT 2; normalização, lotes, ACK manual e recuperação |
| Inferência | Regras Python de debounce, passagem, direção e projeção temporal |
| Dados | PostgreSQL 16, SQLAlchemy 2, Alembic; idempotência e integridade relacional |
| Laboratório | Flet; simulação visual e observadores MQTT/banco/ingestor |
| Ambiente | Docker Compose; execução local ou serviços externos configuráveis |

`api/`, `db/` e `rfid_*/` contêm o backend; `frontend/` contém a interface. `tools/` reúne o laboratório; `scripts/`, os comandos auxiliares; `config/`, as configurações e exemplos; `requirements/`, as dependências; `deploy/`, o Compose e o Dockerfile. Os arquivos de controle do Git e as orientações de agentes permanecem na raiz por seu escopo técnico. [Guia do código e contratos](docs/reference/code-guide.md).

## Documentação técnica e verificações

```bash
python -m pip install -r requirements/dev.txt
python -m ruff check --config config/ruff.toml .
python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
python scripts/documentation.py --check
python scripts/documentation.py --html
```

Os testes de banco exigem `TEST_DATABASE_URL` para PostgreSQL local **descartável**; a suíte limpa suas tabelas. Integrações MQTT são habilitadas por `RUN_MQTT_INTEGRATION=1`. Veja [como reproduzir as validações](docs/operations/validation.md). Docstrings Python podem ser consultadas por `python -m pydoc api.service_busca_ativos`; o gerador cria HTML navegável em `docs/reference/html/`.

Para mais detalhes, **acesse a [documentação no repositório](docs/README.md)**:

- [Execução e configuração dos quatro modos](docs/operations/execution.md)
- [Arquitetura, fluxos e limites de persistência](docs/architecture/system-overview.md)
- [Modelo de dados](docs/architecture/data-model.md) e [diagrama de entidades](docs/architecture/er-diagrama.mermaid)
- [Módulos, funções e geração de documentação pydoc](docs/reference/code-guide.md)
- [Ordenação estável das tabelas](docs/implementations/ordenacao-estavel-tabelas.md)
- [Laboratório e simulador visual](docs/lab_test_launcher.md)
- [Experimentos e evidências](docs/experiments/README.md)
- [Decisões de arquitetura](docs/decisions/README.md)
