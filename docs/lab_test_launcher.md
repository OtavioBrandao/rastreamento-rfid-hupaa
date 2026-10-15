# Launcher de testes de laboratório RFID

## Problema e importância para o MVP

Um teste físico pode estabelecer conexão MQTT e ainda rejeitar todas as leituras
porque faltam leitor, antenas, zonas ou o mapeamento lógico do portal. O launcher
prepara esses cadastros antes de iniciar o ingestor e abre três observadores para
acompanhar a sequência MQTT → ingestão → `leituras_brutas`.

## O que foi implementado

`python -m tools.lab_launcher` limpa a tela e mostra quatro escolhas: local com
simulador visual, local com leitor físico, broker/banco externos com leitor físico e
broker/banco externos com simulador visual. No modo local, também pergunta se
deve reaproveitar os dados. O modo sem perguntas usa as flags equivalentes:

```bash
python -m tools.lab_launcher
python -m tools.lab_launcher start --env local --source synthetic
python -m tools.lab_launcher start --env local --source physical --reader-id reader-01
python -m tools.lab_launcher start --env local --source physical --tag "3034000000000C40000000E8=Bomba de infusão 01"
python -m tools.lab_launcher start --env managed --source physical --mqtt-transport plain --tag "3034000000000C40000000E8=Bomba de infusão 01"
python -m tools.lab_launcher start --env managed --source synthetic --env-file config/environments/.env.cloud
python -m tools.lab_launcher stop --env local
python -m tools.lab_launcher stop --env local --clear-ports
```

Com leitor físico (opções 2 e 3), o launcher não abre o simulador: depois das
migrations lista os EPCs lidos nas últimas 24 horas e pergunta quais tags
cadastrar e o nome do equipamento de cada uma (`--tag EPC=Nome` sem menu). No
broker externo (opções 3 e 4), pergunta também o transporte: `mqtts` (TLS, 8883)
ou `mqtt` sem TLS (1883, `--mqtt-transport plain`). Veja o
[hotfix de tags físicas e MQTT sem TLS](implementations/hotfix-lab-tags-fisicas-mqtt-sem-tls.md).

Nos testes sintéticos (opções 1 e 4), depois do ingestor saudável o launcher abre
o **simulador visual** (`python -m tools.lab_simulator`), uma janela Flet com a
mesma planta do mapa EASY: salas A e B, leitor 01, portal e as antenas A
(porta 1) e B (porta 2), cada uma com um círculo de alcance. Na janela:

1. Informe a quantidade de itens (1 a 12) e clique em **Definir nomes**.
2. Dê um nome a cada item e clique em **Gerar itens no mapa**. Cada item recebe
   um EPC aleatório de 96 bits (prefixo `E2804C41`) e é cadastrado no banco do
   ensaio como equipamento do tipo sintético, com o nome escolhido. Os itens
   aparecem em posições sorteadas, sempre fora do alcance das antenas;
   **Novas posições** sorteia de novo.
3. Arraste um item com o botão esquerdo. Dentro de um círculo, a antena gera uma
   leitura a cada 0,2 s, com RSSI de -5700 (sobre a antena) a -6700 (na borda);
   o círculo pulsa e o item fica verde. Para gerar passagem, saia do alcance de
   uma antena e entre no da outra em até 3 s (`RFID_PASSAGE_MAX_INTERVAL_MS`).

A publicação usa uma thread própria com QoS 1 e não espera cada PUBACK; o
simulador falha e mostra o erro se uma mensagem ficar mais de 10 s sem PUBACK ou
se a conexão cair. O cabeçalho da janela mostra destino, leituras publicadas,
pendentes e a contagem por antena. Os pulsos do mapa EASY no dashboard vêm das
leituras gravadas no banco, então acompanham o simulador em tempo real. O
alcance, o RSSI e o período são ilustrativos, sem calibração física. Os roteiros
fixos anteriores (`--scenario`, `--count`, `--messages`, `--interval`, `--epc`,
`--single`) e a conferência automática no banco foram removidos.

O launcher usa `--timestamp-format counter` por padrão tanto no teste físico
quanto no sintético. O simulador usa os campos JSON observados
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

- Python 3.12 e `pip install -r requirements/lab.txt` no host (inclui o Flet do
  simulador visual; na primeira execução o Flet baixa o cliente desktop).
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
- O observador MQTT usa `paho-mqtt` já presente em `requirements/base.txt`; não
  precisa instalar `mosquitto_sub` no host. No modo interativo o launcher
  acompanha o teste até `Ctrl+C`. Os três observadores usam um sinal de sessão:
  `Ctrl+C` ou `stop` encerra os observadores e os serviços Compose. As abas de
  terminal podem permanecer abertos com o histórico para inspeção. `stop`
  confirma que as portas locais ficaram livres e oferece encerrar outros
  processos que ainda as ocupem; `--clear-ports` faz essa limpeza sem pergunta.
  Em execução sem terminal (`--no-terminals`), use `stop` para encerrar o Compose.
  Com o simulador e `--no-terminals`, o launcher espera a janela ser fechada.

No modo `managed`, configure `config/environments/.env.cloud` fora do Git com broker e banco de
testes. O launcher pede campos ausentes e oferece salvá-los no arquivo ignorado
pelo Git. `DATABASE_URL` deve apontar para o banco de migrations/seed e
`APP_DATABASE_URL` para o banco de ingestão. O modo `managed` nunca executa
`down -v`. A operação não configura hotspot no notebook.
No cenário externo sintético, use uma credencial MQTT de publicação diferente
da credencial de assinatura do ingestor. O launcher usa automaticamente
`config/environments/.env.cloud.reader-01` se existir; senão, o menu pede o caminho. Em execução
sem menu, passe `--publisher-env-file config/environments/.env.cloud.reader-01`. O arquivo é local
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
cadastro base (criado ou reutilizado) e a abertura do simulador. Se
uma etapa falhar, a mensagem identifica a etapa e mostra as últimas linhas do
comando ou do serviço com falha. Senhas e URLs com credenciais são ocultadas
nessas mensagens. Use os três terminais de observação para acompanhar a
publicação MQTT, os logs do ingestor e as leituras gravadas no banco. Em caso
de erro, o launcher encerra os serviços Compose que iniciou; os logs da falha
são exibidos antes da limpeza.
