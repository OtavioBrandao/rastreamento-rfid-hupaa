# Launcher de testes de laboratório RFID

## Problema e importância para o MVP

Um teste físico pode estabelecer conexão MQTT e ainda rejeitar todas as leituras
porque faltam leitor, antenas, zonas ou o mapeamento lógico do portal. O launcher
prepara esses cadastros antes de iniciar o ingestor e abre três observadores para
acompanhar a sequência MQTT → ingestão → `leituras_brutas`.

## O que foi implementado

`python -m tools.lab_launcher` limpa a tela e mostra quatro escolhas: local com
simulador web, local com leitor físico, broker/banco externos com leitor físico e
broker/banco externos com simulador web. No modo local, também pergunta se
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

Nos testes sintéticos (opções 1 e 4) o launcher **não abre aplicativo
desktop**: o simulador agora é web. `python scripts/dev.py --teste 1` sobe a API
com `SIMULADOR_HABILITADO=true` e abre o navegador em `#/simulador`, onde se
escolhe a planta **Laboratório EASY** (mesmas salas A/B, portal e antenas A e B
do simulador anterior) ou **Hospital HUPAA**. Iniciada a simulação, o link de
controle (`#/simulador/controle/<código>`) abre em outra aba para adicionar e
arrastar os equipamentos. Na opção 4 a API usa a credencial de publicação de
`config/environments/.env.cloud.reader-01`, que precisa permitir os tópicos dos
leitores virtuais (`MQTT_TOPIC=easy/dev/hupaa/+/+/readings` no perfil; `#` é
recusado). Detalhes em [simulador web](implementations/simulador-web.md).

Os equipamentos não são mais cadastrados pela janela: crie itens virtuais
"etiquetados, não cadastrados" e cadastre-os em **Cadastro → por leitura RFID**,
ou use o EPC de um equipamento já cadastrado. Alcance, RSSI (−5700 a −6700) e
período de 0,2 s continuam ilustrativos, sem calibração física.

O launcher usa `--timestamp-format counter` por padrão tanto no teste físico
quanto no sintético. O simulador web usa os campos JSON observados
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

- Python 3.12 e `pip install -r requirements/lab.txt` no host. Não há
  dependência gráfica desktop: o simulador roda no navegador.
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
cadastro base (criado ou reutilizado) e o endereço do simulador web. Se
uma etapa falhar, a mensagem identifica a etapa e mostra as últimas linhas do
comando ou do serviço com falha. Senhas e URLs com credenciais são ocultadas
nessas mensagens. Use os três terminais de observação para acompanhar a
publicação MQTT, os logs do ingestor e as leituras gravadas no banco. Em caso
de erro, o launcher encerra os serviços Compose que iniciou; os logs da falha
são exibidos antes da limpeza.
