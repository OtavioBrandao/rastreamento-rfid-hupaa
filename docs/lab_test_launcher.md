# Launcher de testes de laboratório RFID

## Problema e importância para o MVP

Um teste físico pode estabelecer conexão MQTT e ainda rejeitar todas as leituras
porque faltam leitor, antenas, zonas ou o mapeamento lógico do portal. O launcher
prepara esses cadastros antes de iniciar o ingestor e abre três observadores para
acompanhar a sequência MQTT → ingestão → `leituras_brutas`.

## O que foi implementado

`python -m tools.lab_launcher` limpa a tela e mostra quatro escolhas: local com dados
sintéticos, local com leitor físico, broker/banco externos com leitor físico e
broker/banco externos com dados sintéticos. No modo local, também pergunta se
deve reaproveitar os dados. O modo sem perguntas usa as flags equivalentes:

```bash
python -m tools.lab_launcher
python -m tools.lab_launcher start --env local --source synthetic --passage
python -m tools.lab_launcher start --env local --source synthetic --count 2 --messages 100
python -m tools.lab_launcher start --env local --source synthetic --scenario 2
python -m tools.lab_launcher start --env managed --source synthetic --scenario 3 --env-file .env.cloud
python -m tools.lab_launcher start --env local --source physical --reader-id reader-01
python -m tools.lab_launcher start --env managed --source synthetic --env-file .env.cloud
python -m tools.lab_launcher stop --env local
python -m tools.lab_launcher stop --env local --clear-ports
```

Depois da escolha do ambiente (1–4), o modo interativo pergunta qual roteiro
executar. `--scenario 1|2|3` faz a mesma seleção sem interação. O roteiro 1
mantém o ensaio original de uma tag (ou `--count` tags independentes) em A → B;
`--single` mantém a tag na antena A sem passagem. Os roteiros 2 e 3 usam por
padrão os EPCs terminados em **02** e **03** e exigem exatamente dois EPCs se
`--epc` for usado. Neles, `--messages` indica leituras por travessia, com mínimo
de 10; `--interval` define a pausa entre lados do portal. O roteiro 2 faz 02
A → B, depois 02 B → A enquanto 03 A → B, e depois 02 A → B enquanto 03
B → A. O roteiro 3 faz 02 A → B e a mantém lá; 03 atravessa A → B → A → B → A.
Leituras de tags que se movem ao mesmo tempo são intercaladas; há 3,5 segundos
entre fases para permitir novas passagens da mesma tag. Em modos físicos, o
mesmo menu mostra o percurso como guia manual, sem publicar leituras sintéticas.
O payload JSON e o cálculo de `event_id` do ingestor não foram alterados.

`--reuse` reaproveita dados sem perguntar. `--fresh` executa
`docker compose down -v` somente no modo local e apaga os
volumes de laboratório. Ao iniciar, o launcher verifica os contêineres e os
processos do host que escutam nas portas TCP locais de MQTT e PostgreSQL. Ele
mostra nome e PID e pede confirmação antes de encerrá-los; `--force` dispensa
essa confirmação. Não encerra o daemon Docker nem um processo sem PID acessível.
Se faltar permissão ou uma porta continuar indisponível, o teste é interrompido
com erro em vez de alegar que a porta foi liberada. Contêineres do próprio
projeto são reaproveitados. `--no-terminals` permite execução sem interface
gráfica. `--count`, `--messages`, `--interval`, `--epc` e `--single` controlam
as publicações sintéticas. O padrão usa um EPC fixo de laboratório e publica
**100 mensagens** em quatro etapas: 15 na aproximação da antena 1, 45 enquanto
o item fica parado nessa antena, 10 ao sair da antena 1 e 30 ao atravessar a
antena 2. A permanência dura cerca de sete segundos. `--interval` controla a
pausa antes da antena 2 (500 ms por padrão), maior que a tolerância inicial de
ambiguidade da direção (100 ms). `--count 2` simula dois itens e publica 100
mensagens para cada um. Os valores de RSSI variam ilustrativamente entre
-6700 e -5700, na faixa das leituras exibidas pelo leitor, sem calibração
física do sinal.
Os EPCs padrão são reutilizados entre execuções; `--epc` permite informar EPCs
hexadecimais próprios. O seed associa os EPCs sintéticos a equipamentos de
laboratório antes da publicação, para que passagem confirmada também gere
histórico de movimentação e última zona. Vínculos existentes são preservados.
O launcher consulta o banco após publicar e informa, por EPC, as leituras
persistidas, a passagem, o movimento e a última zona. Para permitir a ingestão
mais lenta em banco externo, aguarda enquanto houver progresso: falha após 30
segundos sem novas leituras ou ao atingir o limite total de cinco segundos por
mensagem esperada. Depois da última leitura, há até 30 segundos para a passagem
e o movimento serem confirmados. A conferência usa o intervalo do contador
sintético desta execução, para não contar mensagens pendentes de ensaios
anteriores com o mesmo EPC. `--single` mantém
o item na antena 1 e valida somente as leituras, sem esperar passagem.

O launcher usa `--timestamp-format counter` por padrão tanto no teste físico
quanto no sintético. O publicador sintético usa os campos JSON observados
(`epc`, `rssi`, `antenna`, `timestamp`) na mesma ordem do JSON capturado do leitor,
em JSON compacto e sem `readerid` no corpo. O identificador do leitor vem do tópico MQTT. O
`timestamp` é uma string numérica de sete dígitos, crescente durante o ensaio;
seu valor é sintético e não presume a unidade do contador físico. O adapter
EZ700 interpreta qualquer timestamp numérico como contador e usa o horário de
recebimento para o evento canônico, inclusive quando o perfil legado
`epoch_ms` está configurado. No modo físico, `--timestamp-format` também aceita
`rfc3339` e `epoch_ms` por compatibilidade de configuração; esses valores não
convertem números em datas. O contador original permanece na auditoria.

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
- Windows 11: Docker Desktop com backend WSL2. O launcher abre três abas
  nomeadas **MQTT**, **Ingestor** e **Banco** no Windows Terminal. Se `wt.exe`
  não estiver disponível, abre janelas `cmd.exe` com esses títulos. O launcher
  espera cada observador iniciar e recupera em janela separada uma aba que
  falhou; se ainda houver falha, informa o observador pelo nome. O script recebe
  o Python e o tipo de observador por argumentos explícitos. A configuração
  sensível fica em `.lab_launcher/`, ignorada pelo Git, até o encerramento da
  sessão. O terminal Banco mostra quando está conectado e aguardando leituras.
  O comando Python deve ser executado no Windows, no mesmo ambiente virtual
  usado para instalar as dependências.
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
No cenário externo sintético, use uma credencial MQTT de publicação diferente
da credencial de assinatura do ingestor. O launcher usa automaticamente
`.env.cloud.reader-01` se existir; senão, o menu pede o caminho. Em execução
sem menu, passe `--publisher-env-file .env.cloud.reader-01`. O arquivo é local
e ignorado pelo Git. Configure nele `MQTT_USERNAME`, `MQTT_PASSWORD` e o
`MQTT_TOPIC` exato autorizado para Publish. Conectar ao broker não comprova
essa permissão: se não houver PUBACK QoS 1, o launcher informa se houve
desconexão ou timeout e interrompe o teste.

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
