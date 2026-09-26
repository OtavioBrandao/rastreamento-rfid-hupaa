# Launcher de testes de laboratório RFID

## Problema e importância para o MVP

Um teste físico pode estabelecer conexão MQTT e ainda rejeitar todas as leituras
porque faltam leitor, antenas, zonas ou o mapeamento lógico do portal. O launcher
prepara esses cadastros antes de iniciar o ingestor e abre três observadores para
acompanhar a sequência MQTT → ingestão → `leituras_brutas`.

## O que foi implementado

`python -m tools.lab_launcher start` mostra quatro escolhas: local com dados
sintéticos, local com leitor físico, broker/banco externos com leitor físico e
broker/banco externos com dados sintéticos. No modo local, também pergunta se
deve reaproveitar os dados. O modo sem perguntas usa as flags equivalentes:

```bash
python -m tools.lab_launcher start --env local --source synthetic --passage
python -m tools.lab_launcher start --env local --source synthetic --count 5 --repeats 4
python -m tools.lab_launcher start --env local --source physical --reader-id reader-01
python -m tools.lab_launcher start --env managed --source synthetic --env-file .env.cloud
python -m tools.lab_launcher stop --env local
python -m tools.lab_launcher stop --env local --clear-ports
```

`--reuse` reaproveita dados sem perguntar. `--fresh` executa
`docker compose down -v` somente no modo local e apaga os
volumes de laboratório. Ao iniciar, o launcher verifica os contêineres e os
processos do host que escutam nas portas TCP locais de MQTT e PostgreSQL. Ele
mostra nome e PID e pede confirmação antes de encerrá-los; `--force` dispensa
essa confirmação. Não encerra o daemon Docker nem um processo sem PID acessível.
Se faltar permissão ou uma porta continuar indisponível, o teste é interrompido
com erro em vez de alegar que a porta foi liberada. Contêineres do próprio
projeto são reaproveitados. `--no-terminals` permite execução sem interface
gráfica. `--count`, `--repeats`, `--burst-interval`, `--interval`, `--epc` e
`--single` controlam as publicações sintéticas. O padrão usa três EPCs fixos
de laboratório e publica três leituras em cada antena, totalizando 18
mensagens. Para cada EPC, `--passage` publica uma rajada na porta 1 e outra na
porta 2, nessa ordem. `--burst-interval` controla o intervalo dentro da rajada
(80 ms por padrão); `--interval` controla a pausa entre antenas (500 ms por
padrão), maior que a tolerância inicial de ambiguidade da direção (100 ms).
Os EPCs padrão são reutilizados entre execuções; `--epc` permite informar EPCs
hexadecimais próprios. O seed associa os EPCs sintéticos a equipamentos de
laboratório antes da publicação, para que passagem confirmada também gere
histórico de movimentação e última zona. Vínculos existentes são preservados.
O launcher consulta o banco após publicar e informa, por EPC, as leituras
persistidas, a passagem, o movimento e a última zona. Se o resultado não surgir
em 30 segundos, a etapa falha com o último estado observado. `--single` valida
somente as leituras, sem esperar passagem.

O launcher usa `--timestamp-format counter` por padrão tanto no teste físico
quanto no sintético. O publicador sintético usa os campos JSON observados
(`epc`, `timestamp`, `rssi`, `antenna`, `readerid`) com contador artificial
crescente. Isso testa a normalização do contador sem afirmar unidade ou formato
completo do relógio físico. `--timestamp-format rfc3339` testa o outro perfil;
no modo físico também é possível usar `epoch_ms` se o leitor estiver configurado
dessa forma. O contador original permanece na auditoria e o horário canônico
vem do recebimento.

O seed usa `reader-01` por padrão, cria um andar e setor exclusivos de laboratório,
zonas A/B, portal, duas antenas e seus mapeamentos lógicos ativos. Pode ser
reexecutado sem duplicação. Caso encontre topologia ou serial explicitamente
informado divergente, interrompe o teste em vez de modificar cadastro existente.
Para um leitor físico com outro identificador, passe `--reader-id` e, se conhecido,
`--serial` com o número de série real.
No modo local, a URL do banco usada pelo seed e pelo observador é construída a
partir de `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` e `POSTGRES_PORT`;
uma `DATABASE_URL` externa exportada no shell não será usada nesse modo.

## Pré-requisitos

- Python 3.12 e `pip install -r requirements.txt` no host.
- Windows 11: Docker Desktop com backend WSL2. O launcher abre três consoles
  `cmd.exe` separados, evitando falhas de interpretação de argumentos no
  Windows Terminal e mensagens do PSReadLine. O comando Python deve ser executado
  no Windows, no mesmo ambiente virtual usado para instalar as dependências.
- Ubuntu 24.04: Docker Engine com plugin Compose e permissão para usar Docker.
  `gnome-terminal`, `konsole`, `xterm`, `x-terminal-emulator` ou `tmux` para os
  três painéis. Sem `DISPLAY`/`WAYLAND_DISPLAY` (inclusive WSL2 sem servidor
  gráfico), o launcher escolhe `tmux`; instale-o para esse ambiente.
- O observador MQTT usa `paho-mqtt` já presente em `requirements.txt`; não
  precisa instalar `mosquitto_sub` no host. No modo interativo o launcher
  acompanha o teste até `Ctrl+C`. Os três observadores usam um sinal de sessão:
  `Ctrl+C` ou `stop` encerra os observadores e os serviços Compose. As abas de
  terminal podem permanecer abertos com o histórico para inspeção. `stop`
  confirma que as portas locais ficaram livres e oferece encerrar outros
  processos que ainda as ocupem; `--clear-ports` faz essa limpeza sem pergunta.
  Em execução sem terminal (`--no-terminals`), use `stop` para encerrar o Compose.

No modo `managed`, configure `.env.cloud` fora do Git com broker e banco de
testes. O launcher pede campos ausentes e oferece salvá-los no arquivo ignorado
pelo Git. `DATABASE_URL` deve apontar para o banco de migrations/seed e
`APP_DATABASE_URL` para o banco de ingestão. O modo `managed` nunca executa
`down -v`. A operação não configura hotspot no notebook.
Se a ACL do broker reservar credenciais distintas para publicação, passe
`--publisher-env-file .env.cloud.reader-01` (arquivo local ignorado pelo Git).

## Sequência e limites

O launcher espera a saúde de PostgreSQL e Mosquitto locais, aplica Alembic,
executa o seed no banco de testes e só então inicia o ingestor. O healthcheck
do ingestor confirma conectividade MQTT e uma consulta simples ao banco. Abre observação
MQTT, logs do ingestor e polling de leituras, passagens, movimentos e última
zona. Dados sintéticos seguem o contrato atualmente aceito pelo adapter
`ez700`; isso não declara o formato completo do payload físico.
A janela de passagem e o debounce ainda precisam de calibração física no HUPAA.
Sem Docker disponível, use `--help` para verificar as opções, mas o fluxo de
ponta a ponta exige um daemon Docker ativo e acesso ao broker/banco.

Durante a execução, o terminal principal mostra o cenário, o arquivo de
configuração, o progresso do Compose e do build, as migrations, o resultado do
cadastro base (criado ou reutilizado) e cada leitura sintética publicada. Se
uma etapa falhar, a mensagem identifica a etapa e mostra as últimas linhas do
comando ou do serviço com falha. Senhas e URLs com credenciais são ocultadas
nessas mensagens. Use os três terminais de observação para acompanhar a
publicação MQTT, os logs do ingestor e as leituras gravadas no banco. Em caso
de erro, o launcher encerra os serviços Compose que iniciou; os logs da falha
são exibidos antes da limpeza.
