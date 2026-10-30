# Teste 1 sem internet ou Wi-Fi

## Problema e importância para o MVP

A demonstração precisa iniciar e funcionar mesmo sem Wi-Fi, usando as simulações
já salvas no notebook. Antes, o teste 1 reconstruía a imagem Docker em toda subida
(podendo consultar o registry e o pip) e tentava instalar o frontend se faltasse
`node_modules`. Essas etapas podiam impedir a apresentação sem internet.

## O que foi feito

O teste 1 (`local` + `synthetic`) agora opera offline por padrão, inclusive com
os atalhos existentes no Ubuntu:

```bash
rfid-teste1
# Em outro terminal, ao terminar:
rfid-parar
```

`rfid-teste1` continua chamando `scripts/dev.py --teste 1 --reaproveitar`.
Nenhuma alteração nos atalhos é necessária. O banco, os layouts e os arquivos
locais continuam sendo reaproveitados; não selecione limpeza de volumes se quiser
manter esses dados.

PostgreSQL, Mosquitto, ingestor, API, interface e simulador comunicam-se pelo
próprio notebook (loopback e rede virtual Docker). Isso funciona com Wi-Fi
desligado e sem cabo de rede. As plantas e os recursos da interface são locais.
O simulador força o broker local, mesmo se houver configuração de broker externo
em variáveis `SIMULADOR_MQTT_*`. As sondas HTTP ignoram proxies externos.

O launcher verifica as imagens instaladas antes de iniciar ou limpar serviços.
Todos os comandos de subida do teste 1 usam `--pull never --no-build`. O arquivo
`deploy/compose.offline.yaml` monta código e migrations atuais como somente
leitura, reutilizando as dependências já presentes na imagem. Assim, uma mudança
de código não exige reconstrução durante a apresentação. A pasta de dados mantém
a montagem gravável original. Dependências do frontend ausentes geram uma mensagem
local em vez de uma instalação automática. O npm recebe modo offline e a
notificação de atualização desativada. Os demais testes mantêm seu fluxo.

`rfid-parar` continua encerrando os processos e o Compose sem apagar volumes.
`stop` não executa downloads nem build e reconhece o mesmo projeto Docker.

## Preparação prévia do notebook

Instalação e atualização de dependências devem ser feitas **antes** da
demonstração, enquanto houver internet. Não são etapas do teste 1:

```bash
.venv/bin/python -m pip install -r requirements/lab.txt
npm --prefix frontend ci
docker compose -f deploy/compose.yaml --env-file config/environments/.env.local --profile local pull postgres mosquitto
docker compose -f deploy/compose.yaml --env-file config/environments/.env.local --profile local build migrate-local ingestor-local
```

As imagens esperadas são `postgres:16.15-alpine`,
`eclipse-mosquitto:2.1.2-alpine` e `rfid-hospital-mvp:dev`.
Não remova essas imagens, `.venv`, `frontend/node_modules` ou os dados locais
antes da apresentação. Se mudar `requirements/base.txt`, atualize a imagem na
preparação. A primeira configuração de usuário também deve estar pronta.

Para ensaiar: execute `rfid-parar`, desligue o Wi-Fi, execute `rfid-teste1`, abra
uma simulação salva, mova equipamentos e confira leituras/passagens no painel.
Encerre com `rfid-parar` e repita a subida para conferir persistência. Não há
necessidade de hotspot nem serviços em nuvem.

## Validação automatizada

```bash
.venv/bin/python -m pytest -q tests/test_teste1_offline.py tests/test_lab_launcher.py tests/test_compose.py
```

As regressões verificam bloqueio de pull/build, falha antes de apagar volumes
quando falta uma imagem, ausência de instalação automática, broker local,
sondas sem proxy e montagens de código/dados. Testes de banco desse conjunto
exigem PostgreSQL descartável em `TEST_DATABASE_URL`.

## Resultado no notebook em 29/10/2026

- Laboratório descartável `rfid-offline-check`, portas 15441/18891: imagens
  existentes, migrations concluídas e ingestor saudável, sem pull/build.
- 94 testes de launcher, Compose, simulador e trajetos aprovados com banco
  descartável explícito. Após adicionar o último caso de ativação automática
  do modo offline, os 9 testes específicos de offline passaram novamente.
- Publicação MQTT real: 5 PUBACKs e 5 leituras persistidas no banco descartável.
- API e Vite responderam em portas separadas (18010/15173), com proxies HTTP/HTTPS
  apontando para um endereço local indisponível; módulos do frontend foram
  servidos localmente.
- Ruff, verificação de docstrings e `git diff --check` aprovados.

O Wi-Fi do notebook não foi desligado por esta validação. O ensaio verifica o
fluxo local e a ausência das etapas de download/build; o procedimento acima
permite repetir a demonstração com Wi-Fi desligado.
