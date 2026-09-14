# ISS-004 — Integração contínua

## O que é

Integração contínua (CI) é a execução automática de verificações do repositório pelo
GitHub. Neste projeto, o workflow `.github/workflows/ci.yml` é acionado em pushes para
`main` e em Pull Requests direcionados a `main`.

## Problema

Sem CI, uma alteração de um integrante pode quebrar código que já funcionava para o
outro. O problema pode aparecer tarde, quando as mudanças já estão misturadas.

## Objetivo

Executar automaticamente verificações de qualidade, testes e criação do schema sempre
que código chegar à branch principal ou for proposto por Pull Request.

## Fluxo

```mermaid
flowchart LR
    DEV[Desenvolvedor] --> PUSH[Push / Pull Request]
    PUSH --> GH[GitHub Actions]
    GH --> LINT[Lint]
    GH --> TEST[Testes]
    GH --> MIG[Migrations]
    MIG --> PG[(PostgreSQL efêmero)]
```

Os três jobs são independentes e executam em paralelo. Assim, uma falha informa
diretamente se o problema está em `Lint`, `Testes` ou `Migrations`.

## O que cada etapa verifica

- **Lint:** usa Ruff para detectar erros básicos de Python, imports não usados ou
  indefinidos e problemas de organização dos imports. A formatação de imports é uma
  etapa separada e visível dentro do job; o formatador global não foi imposto neste
  baseline para evitar uma alteração massiva sem relação funcional com a issue.
- **Testes:** executa pytest com os testes unitários e inicia o Mosquitto local para
  habilitar a integração MQTT existente. Não acessa leitor físico, HUPAA ou HiveMQ.
- **Migrations:** instala as dependências da aplicação, aplica `alembic upgrade head`
  em um banco vazio e exibe a revisão aplicada com `alembic current`.

O cache usado por `actions/setup-python` considera `requirements.txt` e
`requirements-dev.txt`; somente pacotes do pip são armazenados, nunca variáveis ou
segredos de ambiente.

## PostgreSQL efêmero

O job `Migrations` cria um serviço PostgreSQL 16 exclusivo para aquela execução. O
banco usa credenciais sintéticas declaradas no workflow, tem health check com
`pg_isready` e é descartado junto com o runner.

Esse banco **não é o Neon**, não é compartilhado e não usa credenciais de produção ou
desenvolvimento. A URL é fornecida somente ao job de migrations e não é impressa pelos
comandos do workflow.

## Como executar localmente

Prepare o ambiente, em Ubuntu 24.04:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Lint e formatação de imports, equivalentes às etapas do job `Lint`:

```bash
python -m ruff check --select E4,E7,E9,F .
python -m ruff check --select I .
```

Testes unitários, sem serviço externo:

```bash
python -m pytest -q
```

Para reproduzir também a integração viável no CI com o Compose já existente:

```bash
docker compose up -d mosquitto
RUN_MQTT_INTEGRATION=1 TEST_MQTT_PORT=1883 python -m pytest -q
docker compose down --volumes --remove-orphans
```

Enquanto o ambiente PostgreSQL padronizado da ISS-003 não estiver integrado à `main`,
a validação de migration pode usar um contêiner temporário equivalente ao serviço do
workflow:

```bash
docker run --detach --rm --name rfid-ci-iss004 \
  -e POSTGRES_DB=rfid_ci \
  -e POSTGRES_USER=rfid_ci \
  -e POSTGRES_PASSWORD=rfid_ci_only \
  -p 127.0.0.1:55432:5432 postgres:16-alpine
until docker exec rfid-ci-iss004 pg_isready -U rfid_ci -d rfid_ci; do sleep 1; done
export DATABASE_URL='postgresql+psycopg2://rfid_ci:rfid_ci_only@localhost:55432/rfid_ci'
alembic upgrade head
alembic current
docker stop rfid-ci-iss004
unset DATABASE_URL
```

As credenciais acima são descartáveis e existem somente no contêiner local. Após a
integração da ISS-003, deve-se preferir o comando de migration do ambiente Compose
padronizado por ela.

## Como interpretar uma falha

- `Lint` vermelho: erro básico de código Python ou imports fora do baseline.
- `Testes` vermelho: comportamento incorreto, regressão ou falha da integração local.
- `Migrations` vermelho: o schema atual não pôde ser recriado em PostgreSQL vazio.

Abra o job vermelho e localize a primeira etapa que falhou. Os nomes das etapas
correspondem aos comandos documentados acima.

## Relação com ISS-002c

A ISS-004 consome a interface atual do Alembic; ela não cria nem redesenha migrations.
A ISS-002c (#4) continua aberta. A migration `44ef89b10f17` disponível na `main` foi
validada, mas o job e esta evidência precisam de nova validação quando o contrato final
da ISS-002c for integrado.

## Relação com ISS-003

A ISS-003 padroniza o ambiente local com Docker. A ISS-004 valida automaticamente o
repositório no GitHub. Elas se complementam: o ambiente local facilita a reprodução,
enquanto a CI evita que a validação dependa de uma execução manual.

Na `main` usada para esta implementação, a padronização PostgreSQL da ISS-003 ainda não
estava disponível. Por isso o workflow mantém apenas seu serviço efêmero e não altera a
arquitetura Docker pertencente à ISS-003.

## Validação realizada

Em 13/09/2026, na branch `feat/iss-004-ci-lint-tests`:

- `python -m ruff check --select E4,E7,E9,F .`: aprovado.
- `python -m ruff check --select I .`: aprovado.
- `python -m pytest -q`: 30 aprovados e 4 ignorados legitimamente (integração MQTT
  opt-in e OpenSSL ausente no host Windows).
- suíte com Mosquitto e `RUN_MQTT_INTEGRATION=1`: 31 aprovados e 3 ignorados
  legitimamente (OpenSSL ausente no host Windows).
- `alembic upgrade head`: aprovado em PostgreSQL 16 vazio.
- `alembic current`: `44ef89b10f17 (head)`.
- inspeção do banco: 17 tabelas no schema `public`, contando `alembic_version`.

Falha controlada: foi criado temporariamente `controlled_failure_iss004.py` com
`import os` não utilizado. Ruff reportou `F401` e encerrou com código 1. O arquivo foi
removido, e as duas verificações de qualidade voltaram a passar. A falha não faz parte
do histórico final.

## Pendências

- Confirmar os três jobs na execução real do GitHub Actions aberta por este PR.
- Revalidar o job `Migrations` depois do merge da versão final da ISS-002c.
