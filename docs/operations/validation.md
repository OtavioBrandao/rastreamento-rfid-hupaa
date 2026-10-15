# Validação e reprodução

Execute na raiz com Python 3.12 e dependências instaladas. Os testes de banco
limpam tabelas e recusam host externo; use um PostgreSQL **descartável** separado
do banco da demonstração. Não carregue um perfil operacional para rodar a suíte.

## Verificações sem banco

```bash
python -m pip install -r requirements/dev.txt
python -m ruff check --config config/ruff.toml .
python scripts/documentation.py --check
python -m pytest -q
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
```

Sem `TEST_DATABASE_URL`, testes que precisam de banco são ignorados. Isso não
representa uma validação completa. A referência HTML exige também as dependências
de `requirements/lab.txt`; gere com `python scripts/documentation.py --html`.

## Integração com banco e MQTT

Exemplo Ubuntu 24.04, com portas distintas das do laboratório:

```bash
docker run -d --name rfid-check-pg -e POSTGRES_USER=rfid_test -e POSTGRES_PASSWORD=rfid_test_only -e POSTGRES_DB=rfid_test -p 127.0.0.1:15439:5432 postgres:16.15-alpine
docker run -d --name rfid-check-mqtt -p 127.0.0.1:18889:1883 --mount type=bind,source="$(pwd)/mosquitto/mosquitto.dev.conf",target=/mosquitto/config/mosquitto.conf,readonly eclipse-mosquitto:2.1.2-alpine
export TEST_DATABASE_URL='postgresql+psycopg2://rfid_test:rfid_test_only@127.0.0.1:15439/rfid_test'
export DATABASE_URL="$TEST_DATABASE_URL"
export RUN_MQTT_INTEGRATION=1
export TEST_MQTT_PORT=18889
# Aguarde pg_isready confirmar a inicialização do banco
docker exec rfid-check-pg pg_isready -U rfid_test -d rfid_test
python -m alembic -c config/alembic.ini upgrade head
python -m pytest -q
```

No PowerShell, use `$env:TEST_DATABASE_URL='...'` e equivalentes para as variáveis.
O comando `docker run` com bind mount deve receber o caminho absoluto Windows do
arquivo Mosquitto. O ambiente isolado é o único alvo das limpezas de teste.

Migrations são exercitadas com upgrade em banco vazio, repetição, downgrade e
reaplicação. Casos específicos também verificam dados legados e integridade. As
constraints de associação, hardware, temporalidade e concorrência exigem
PostgreSQL real. Testes MQTT verificam transporte, redelivery, persistência e
resiliência; não medem propagação RF nem calibram antenas.

## Infraestrutura e shell

```bash
docker compose -f deploy/compose.yaml --env-file config/environments/.env.local.example --profile local config --quiet
docker compose -f deploy/compose.yaml --env-file config/environments/.env.cloud.example --profile managed config --quiet
docker build -f deploy/Dockerfile -t rfid-hupaa:check .
bash tests/infrastructure/compose-smoke-test.sh
bash tests/infrastructure/resilience-smoke-test.sh
bash tests/reader-connectivity/mqtt/smoke-test.sh
```

Os smoke tests shell destinam-se ao Ubuntu 24.04 e criam projetos descartáveis.
Mantêm suas portas e volumes separados. O reset de um laboratório local existente
tem proteção própria e exige confirmação explícita; não é necessário para validar
a versão. Todos os `.sh` são versionados com LF por `.gitattributes`.

## Registro da candidata em 15/10/2026

Ambiente principal: Windows 11, Python 3.12.14, PostgreSQL 16.15 e Mosquitto 2.1.2
descartáveis, separados dos dados operacionais. Integrações MQTT habilitadas.

| Verificação | Resultado |
|---|---|
| Suíte Python completa com banco/MQTT | 1.311 aprovados, 93 subtestes aprovados; 3 testes TLS ignorados por ausência de OpenSSL no PATH do Windows |
| TLS no Ubuntu 24.04/WSL com OpenSSL | Os 3 testes ignorados no Windows foram executados separadamente e aprovados |
| Refinamento final de prioridade e configuração Compose | 10 aprovados após manter o bloco de trânsito junto no topo |
| Frontend Vitest | 63 aprovados, incluindo estabilidade quando contagens/horários mudam |
| TypeScript/Vite | Build aprovado |
| Ruff e `git diff --check` | Aprovados |
| Cobertura de docstrings | 1.057 definições em 125 fontes, incluindo migrations |
| Geração pydoc | 107 módulos importáveis e suplemento das definições privadas |
| Imagem Docker | Build aprovado; imports de todos os pacotes de inferência e ausência de `.env*` na imagem conferidos |
| Compose local reorganizado | PostgreSQL/Mosquitto/ingestor saudáveis; migration concluída |
| Sintaxe shell no Ubuntu 24.04/WSL | `bash -n` aprovado nos quatro scripts |
| Ensaio sintético A→B | 12 publicações, 12 leituras, 1 passagem confirmada, 1 movimento, última zona B |
| Links Markdown locais e perfis privados | Nenhum destino ausente; perfis reais confirmados como ignorados pelo Git |

A suíte completa terminou antes do último refinamento dos grupos de prioridade;
as regressões de busca e Compose e toda a suíte frontend foram reexecutadas após
esse ajuste. As verificações mantêm quatro avisos existentes: depreciações de
dependências do cliente HTTP e avisos SQLAlchemy da comparação de migrations
(ciclo entre equipamento/histórico e opção de dialect). Não impediram upgrade,
downgrade e reaplicação no banco descartável.

O ensaio ponta a ponta usou o publicador do simulador sem abrir a janela Flet,
o Compose em portas isoladas e a topologia semeada. O [registro JSON sanitizado](../experiments/ingestion/pipeline-local-2026-10-15.json)
documenta origem e resultados. Não mede latência, alcance ou taxa de acerto RF.

A distribuição Ubuntu do WSL tem integração Docker desativada. Por isso os smoke
tests shell não foram concluídos de ponta a ponta nela. A sintaxe foi conferida
no Ubuntu e o Compose/ensaio foram executados pelo Docker do Windows. A configuração
do WSL não foi alterada. Consulte também as [evidências históricas](../experiments/README.md).

Limites da reprodução: o firmware do leitor e a rede hospitalar não foram
exercitados nesta execução. Nenhum resultado sintético foi apresentado como
medição física. Não houve provisionamento de hospedagem.
