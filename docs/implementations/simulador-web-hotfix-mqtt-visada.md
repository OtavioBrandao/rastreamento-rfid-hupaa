# Hotfix do simulador web: MQTT sem mexer no HiveMQ, antena direcional e área restrita

## O problema

No primeiro uso do simulador web com broker e banco externos (modo 4):

- **MQTT caía em loop.** O simulador conectava ao HiveMQ Cloud e era
  derrubado na primeira publicação ("Unspecified error"). Antes, com o
  simulador Flet, isso não acontecia e nada precisava ser mudado no HiveMQ.
- A planta estava **poluída**: marcadores grandes com nome, zonas pintadas por
  cima das cores do hospital, alcances grandes e circulares.
- Editar áreas era difícil (só o canto inferior direito redimensionava e uma
  área por cima bloqueava a outra).
- Ao arrastar equipamentos, a posição **voltava** ou demorava a atualizar.
- Faltava a lógica que se quer demonstrar: **visada direta** da antena e um
  leitor que **alerta** a entrada na área restrita (escada).

## Importância para o MVP

O simulador é a ferramenta para explicar ao hospital como a detecção funciona.
Ele precisa rodar com a configuração de broker já usada pela equipe, mostrar a
lógica com clareza e nunca apresentar como confirmado algo que o sistema não
confirmou.

## Causa do MQTT

O launcher exige que o perfil de publicação (`.env.cloud.reader-01`) tenha um
**tópico exato**, e a ACL do HiveMQ libera só esse tópico
(`easy/dev/hupaa/portal-01/reader-01/readings`). O simulador Flet publicava
exatamente nele, como `reader-01`. O simulador web passou a publicar cada
leitor virtual no próprio tópico (`.../sim-l<id>/sim-hupaa-03/readings`), que a
ACL não cobre: o HiveMQ, em MQTT 3.1.1, simplesmente fecha a conexão.
Conferido isolando a credencial: conectada e parada, fica no ar; publicando
fora do tópico dela, cai.

## O que foi feito

**Relay pelo tópico autorizado (sem mudar HiveMQ, credenciais nem ACL)**

- Perfil com tópico exato ⇒ `SIMULADOR_MQTT_TOPICO_RELAY`: todos os leitores
  virtuais publicam nesse tópico, e o payload leva `sim_reader_id` e
  `reader_id` iguais ao leitor virtual (`sim-*`).
- O ingestor só aceita `sim_reader_id` em tópicos listados em
  `RFID_RELAY_LEITORES_VIRTUAIS` (vazio por padrão; recusado com
  `APP_ENV=production`) e só para ids `sim-*`. A leitura vai para o leitor
  virtual, nunca para o `reader-01`; `dados_origem.metadata.relay_reader_id`
  registra por onde chegou.
- Um ingestor sem esse suporte (código anterior, de outra pessoa, no mesmo
  broker) **recusa** a mensagem (`reader_id do payload diverge do tópico`) em
  vez de gravá-la como leitor físico.
- O launcher habilita o relay só no ingestor do ensaio sintético externo.
- O erro de publicação mostra o motivo da queda e a provável falta de
  permissão, sem esconder falhas.

**Antena direcional e alcance menor**

- `orientacao` em graus da tela (0° direita, 90° baixo, 180° esquerda, 270°
  cima, diagonais e ângulo livre) e `fator_traseiro` (padrão 0,35). Alcance
  efetivo `r(Δ) = alcance · (f + (1 − f) · ((1 + cos Δ)/2)²)`, na escala de x
  corrigida pela proporção. Motor, RSSI, avisos e desenho usam a mesma
  fórmula (backend `geometria.py`, frontend `services/simulacao.ts`).
- Alcance padrão 4 (antes 6 no HUPAA e 16 no EASY); EASY com 11 e visada para
  dentro das salas. O corpo do leitor não tem alcance.
- Layouts antigos (sem `orientacao`) continuam omnidirecionais. O editor
  oferece **"Aplicar novos padrões de antena"**: visada para o centro da
  própria zona, traseira curta e alcance limitado, sem mexer em posições e
  portais (dá para desfazer; só vale ao salvar).

**Cinco leitores no HUPAA e alerta de área restrita**

- Preset: Leitores 1–2 **Identix EZ700**, 3–4 **DR Max** (portais) e 5
  **DR Max de área restrita** com **uma** antena (sem portal, na zona
  monitorada). Segunda antena opcional.
- `alerta_area_restrita` no leitor; o monitoramento expõe `alertas_restritos`
  calculados **só de `leituras_brutas`** gravadas pelo ingestor: uma leitura
  basta, sem lado A nem passagem, e nenhuma direção é inferida. O controle e
  o monitoramento destacam o alerta.
- A escada continua sem área no preset: você posiciona e marca a zona
  restrita. Nada classifica elevadores automaticamente.

**Planta limpa e edição fácil**

- Cores do hospital visíveis com legenda (roxo corredor, amarelo pacientes,
  vermelho serviço, verde circulação vertical, azul sala de aula, marrom
  administrativo); zonas só com contorno tracejado.
- Leitores, antenas e portais são pontos de 8–10 px com área de clique de
  22 px; detalhes (leitor, modelo, antena, porta, visada, portal) no hover ou
  foco pelo teclado. Cobertura, cabos e nomes ligam e desligam.
- Áreas: alças nas 4 bordas e 4 cantos só na área selecionada; clique
  seleciona a menor área sob o ponteiro (sobreposição não bloqueia); campos
  numéricos; limites da planta respeitados; Esc cancela o arraste; o desfazer
  trata um arraste inteiro como um passo.
- Controles da visada: rosa dos ventos com 8 direções, ângulo livre,
  "todas as direções" e alcance traseiro.

**Arraste em tempo real**

- Envios numerados: só a resposta do último envio libera a posição local;
  respostas antigas ou polling mais lento não desfazem a posição; a posição
  final é sempre enviada ao soltar. Polling de 500 ms entre abas.
- O controle separa as etapas: movimento virtual → área de leitura (cálculo
  da tela) → publicado no MQTT → **confirmado pelo sistema** (leituras
  gravadas, passagens e alertas consultados no monitoramento a cada 1,5 s).

## Validação

- `tests/test_normalization.py`: relay aceito só no tópico habilitado e só
  para `sim-*`; ingestor antigo recusa; leitor físico intacto; produção
  recusa a configuração.
- `tests/test_simulacao.py`: relay pelo pipeline (motor → ingestor →
  inferência) atribuindo ao leitor virtual e confirmando A→B; relay não
  habilitado não grava nada; antena direcional (frente/trás, 90° = baixo,
  RSSI, layout antigo omnidirecional); avisos considerando a visada; cinco
  leitores; alerta de área restrita com uma antena vindo da leitura gravada,
  sem passagem.
- `frontend/src/test/Simulador.test.tsx`: geometria espelhada, padrões para
  layouts antigos, redimensionar por bordas e cantos, seleção pela lista com
  8 alças e campos numéricos, rosa dos ventos, resposta fora de ordem no
  arraste, alerta no controle.
- Navegador (25/10/2026, banco e Mosquitto locais, ingestor em contêiner):
  teste rápido HUPAA, borda arrastada e desfeita num passo, Maca 01 levada
  da Zona 1 à Zona 2 com 12 leituras gravadas e passagem confirmada, posição
  final preservada; Maca 01 na escada ⇒ alerta "1 item na área restrita
  agora" sem nova passagem.
- Layout do vídeo no Neon validado só em leitura: continua válido e
  omnidirecional até aplicar os novos padrões.

## Limitações

- O relay depende do ingestor deste ensaio estar com o código novo e com
  `RFID_RELAY_LEITORES_VIRTUAIS`; o launcher cuida disso no modo 4.
- O formato da cobertura é ilustrativo, sem equivalência com o diagrama de
  radiação real das antenas.
- O alerta de área restrita indica presença lida, não direção nem
  permanência.
