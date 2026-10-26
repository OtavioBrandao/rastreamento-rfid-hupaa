# Ajustes para a apresentação ao HU: trajeto desenhado, relógio da simulação e HU ao vivo no dashboard

## O problema

A apresentação para a CCOMP e a Engenharia Clínica do HU tem duas pessoas: uma
movimenta equipamentos pelo link do simulador e a outra acompanha tudo pelo
dashboard. No ensaio de 25/10/2026, as detecções e transições pareceram erradas
ou atrasadas. Além disso:

- o simulador mostrava antenas, leitores, coberturas e listas operacionais, que
  deveriam ficar só no dashboard;
- arrastar um equipamento já gerava leituras durante o gesto, sem separar o
  planejamento do caminho do movimento efetivo;
- o mapa do dashboard usava a planta de referência, não a configuração salva do
  HU (zonas, leitores e antenas);
- não havia como mostrar, em poucos minutos, um equipamento ficando muito tempo
  sem detecção.

## Importância para o MVP

O dashboard precisa mostrar o que o **sistema** confirmou: leituras gravadas,
passagens com direção confirmada e última zona. Ele não pode mostrar o que o
simulador sabe da posição. Se a demonstração mostrar transições falsas ou com
meio minuto de atraso, a lógica que se quer validar com o hospital perde a
credibilidade.

## Investigação da sessão anterior

**Intervalo analisado: 25/10/2026, das 18h53min31s às 23h20min43s, horário de
Brasília.** São a primeira e a última leitura gravadas; o site foi fechado por
volta das 23h20. A consulta cobriu de 18h30 à meia-noite.

Fontes usadas, todas só para leitura:

- Neon, de `leituras_brutas`: 37.219 leituras.
- Neon, de `passagens`: 17 passagens.
- Neon, de `historico_movimentacoes`: 17 movimentações.
- Neon, de `simulacao_sessoes`: sessão `b567…`, aberta das 19h34 às 23h20, e a
  anterior, `3739…`.
- Log do ingestor do modo 4, em `docker logs`, com horário.
- Log da API, em `data/dev/api.log`.

### Causas comprovadas

1. **Atraso de 11 a 37 s entre a leitura e a transição.**
   - **Medição:** pelo log do ingestor, a inferência (debounce, passagem e
     histórico) processou cada leitura 11 s depois dela na mediana e 20 s no
     percentil 95, chegando a 37 s. O atraso se manteve durante toda a sessão.
     No banco, `registrado_em − movimentada_em` ficou entre 11 e 36 s em todas
     as 17 movimentações.
   - **Causa:** a reconciliação da localização voltava, a cada ciclo, às
     passagens confirmadas de tags **sem equipamento cadastrado** (passagens
     147 a 161, de ensaios anteriores). Cada uma levava cerca de 1,08 s de
     consultas no Neon. O log registrou 13.612 eventos
     `rfid_location_unresolved_epc`, cerca de 15 por ciclo de 16 a 20 s. A
     thread de inferência ficava ocupada com isso, e as leituras novas
     esperavam na fila.
   - **Correção:** `rfid_location/repository.py` só devolve a passagem sem
     movimento quando o EPC tem associação vigente no instante da passagem. É
     a mesma regra de `rfid_movement`. Tags não cadastradas deixam de ser
     reprocessadas sem efeito. Se a associação passar a cobrir aquele instante,
     a passagem volta a ser processada.
2. **Transições impossíveis**, de uma zona onde o equipamento nunca esteve:
   - a bomba …A665 confirmou "Zona 1 → Zona 2" às 19h44min14s e, 7 s depois,
     "Zona 3 → Zona 2";
   - o mesmo aconteceu com a cadeira …6219 às 19h57;
   - às 23h20min03s, a cadeira …6219 confirmou "Zona 2 → Zona 3" 7 s depois de
     "Zona 2 → Zona 1".

   Duas causas se combinaram:
   - **Os itens surgiam dentro da Zona 3.** As posições iniciais eram (8, 94),
     (24, 94) e (40, 94), dentro da área da Zona 3 (y de 70 a 100). Ao sair, o
     item passava pela antena do lado B do portal Zona 2 ↔ Zona 3 (Leitor 3 /
     Antena 1, em (52; 68,9)).
   - **Antena no caminho de outro portal.** A antena do lado A desse mesmo
     portal (Leitor 2 / Antena 2, em (65,8; 29,3)) fica a 4,6 unidades da
     antena B do portal Zona 1 ↔ Zona 2, no caminho Zona 1 → Zona 2.

   O detector guarda o lado já lido sem prazo (`RFID_PASSAGE_MAX_INTERVAL_MS=0`,
   regra existente). A leitura em A minutos depois fechou a passagem com a
   leitura antiga de B. As passagens 165 e 173 confirmam isso: origem na antena
   35 (lado B, Zona 3) e destino na antena 34 (lado A).

   **Correção:** os itens novos agora surgem fora de todas as zonas e fora do
   alcance de toda antena (ver abaixo). O layout do HU **não foi alterado**: a
   antena A do portal Zona 2 ↔ Zona 3 continua no caminho Zona 1 → Zona 2, e
   reposicioná-la é decisão de quem configura a planta.
3. **Interrupção das 19h12 às 19h16.**
   - **Medição:** nenhuma leitura de 19h12min17s às 19h16. No mesmo intervalo:
     - a API registrou porta 8010 ocupada ao reiniciar
       (`[Errno 10048]`, `data/dev/api.log`);
     - o ingestor foi desconectado do broker às 19h13min32s
       (`mqtt_disconnected`, `reason_code` 128) e se reconectou em seguida.
   - **Causa:** o motor de publicação roda dentro da API, então sem API não
     houve publicação. Foi a disputa de porta corrigida em `d46ed9b`.
4. **Volume:** a maca …4C45 ficou parada no alcance das duas antenas da escada
   das 19h51 às 23h20 e gerou 32.584 das 37.219 leituras. Isso é o
   comportamento esperado, mas aumentou a carga do ingestor descrita no item 1.
5. **Nenhuma leitura duplicada:** todas as 37.219 leituras foram `inserted`.
   Houve **uma** leitura fora de ordem (por `id`), sem efeito em passagem.

### Hipóteses, não comprovadas

- **Taxa abaixo da configurada.** Com 2 antenas a 5 leituras/s, um item
  parado deveria gerar cerca de 600 leituras/min, mas foram cerca de 156/min. É
  provável que cada ciclo do motor demore mais que o período de 0,2 s por causa
  das consultas ao Neon, mas isso não foi medido. Isso não altera a ordem das
  leituras: o motor amostra o caminho entre os ciclos (ver abaixo).
- **Perda de mensagens.** Não dá para afirmar se mensagens publicadas durante
  a queda do ingestor das 19h13 se perderam: o broker não registra isso para o
  cliente.

### Configuração preservada

O layout "Hospital HUPAA (padrão)" (id 1, versão 11, salvo às 19h34) e as
sessões foram copiados antes de qualquer mudança para
`data/backups/neon-simulacao-20261025-233758.json`, uma pasta ignorada pelo
Git. Nada foi gravado no Neon nem no HiveMQ. Os testes usam o Postgres
descartável local.

## O que foi feito

### Simulador no link separado (`#/simulador/controle/<código>`)

- **O que aparece:** só a planta, as zonas e os equipamentos. As antenas,
  leitores, coberturas, estágios de detecção, listas de passagem e contadores
  de MQTT saíram desta tela. Uma falha de publicação continua aparecendo,
  porque falhas não são escondidas.
- **Marcadores:** círculos compactos com o símbolo do tipo de equipamento
  (maca, cadeira de rodas, bomba de infusão, monitor ou outro). O nome aparece
  no hover, no foco e durante o desenho.
- **Equipamento novo:** surge no ponto livre mais próximo do centro, procurado
  em espiral. O ponto fica fora de toda zona (com margem), fora do alcance de
  toda antena e longe dos outros itens. Se não houver espaço, o servidor recusa
  em vez de colocar o item numa zona.

### Desenho e execução do trajeto

- **Planejamento:** com o botão esquerdo pressionado, o caminho é desenhado em
  tracejado, com um "fantasma" na ponta.
  - O equipamento não sai do lugar e nada é enviado ao servidor: nenhuma
    leitura, transição ou mudança de ocupação.
  - Parado com o botão pressionado, o tempo parado entra no trajeto, como
    pontos repetidos com `t` maior. Não há timeout por inatividade.
- **Execução:** só começa ao **soltar** o botão.
  - O trajeto vai inteiro para o servidor
    (`POST …/itens/{id}/trajeto`, com pontos `{x, y, t}`), e o motor o
    percorre no relógio da simulação.
  - O motor faz interpolação linear entre os pontos desenhados, sem
    suavização. As pausas desenhadas são preservadas.
  - As duas telas animam a partir do mesmo trajeto e do mesmo relógio.
- **Arraste e cancelamento:** o arraste usa captura do ponteiro, então
  continua fora do marcador e sobre outros elementos.
  - Perda de captura, `pointercancel`, janela sem foco e Esc **cancelam** o
    desenho, sem executar nada e sem deixar o item preso.
  - Botão solto fora da janela (movimento chega com `buttons = 0`) vale como
    soltar.
- **Um trajeto por vez:** um item em trajeto não aceita outro trajeto nem
  movimento direto (409). Pausar a simulação congela o trajeto; retomar
  continua do mesmo ponto, sem teletransporte.
- **Amostragem do motor:** a cada ciclo, o motor avalia o caminho percorrido
  desde o ciclo anterior em passos de no máximo 0,2 s simulados e 0,5 unidade
  de distância.
  - Cada leitura leva o instante simulado em que a tag estava no alcance
    (`sim_lido_em`).
  - Movimento rápido ou tempo acelerado não pulam a antena, e duas antenas
    cruzadas no mesmo ciclo não chegam "juntas" e sem ordem.
  - O limite de uma leitura por item e antena a cada período continua valendo:
    não se criam leituras extras.

### Relógio da simulação (`api/simulacao/relogio.py`)

- **O que muda:** o tempo simulado, `base_sim + (real − base_real) · fator`,
  com fatores ×1, ×2, ×5, ×10, ×30 e ×60. Ele **avança** e **nunca recua**. O
  relógio do computador não é alterado.
- **Quem usa o mesmo relógio:**
  - o motor, nos trajetos e no horário das leituras;
  - o ingestor, que aceita `sim_lido_em` **só** de leitores virtuais `sim-*`,
    fora de produção e nunca antes do recebimento;
  - a recência da API (`get_recency_context`, atenção por ausência de
    detecção) e o monitor.
- **Mesmo tempo nas duas telas:** simulador e dashboard consultam
  `GET /api/simulacao/relogio`. Quando o tempo está acelerado ou adiantado,
  as duas mostram um selo amarelo.
- **O avanço muda o estado real:** a regra de recência, com o limite de
  `RFID_RECENCY_THRESHOLD_MINUTES` (30 min por padrão), passa a ver o
  equipamento como desatualizado de verdade. Nenhuma leitura artificial é
  criada.
- **Recusas:** o avanço é recusado com item em trajeto, porque pularia as
  leituras do caminho.
- **Ao encerrar a sessão:** o fator volta a ×1, e o tempo já adiantado
  continua adiantado.
- **Onde fica guardado:** em `topologia["relogio"]` das sessões, sem tabela
  nova (o banco externo não migra sozinho).

### Dashboard: HU ao vivo (`#/mapa`, aba "Mapa do Hospital")

- **Planta, leitores e antenas:** vêm da **configuração salva do HU**, que é o
  layout da sessão HUPAA aberta.
  - Leitores e antenas aparecem maiores e mais legíveis. A antena é um
    triângulo na direção da visada e pulsa quando há leitura gravada recente.
  - A cobertura pode ser ligada e desligada.
  - Sem sessão do HU aberta, a tela mostra a planta de referência e avisa.
- **Equipamentos:** círculos com o símbolo do tipo, nome e detalhes no hover.
  O estado vem de `monitor.equipamentos`, calculado só com leituras gravadas e
  passagens. Prioridade de cor:
  1. **fora de serviço** (cinza);
  2. **em trânsito**, quando há zona confirmada e a tag foi lida agora por uma
     antena de outra zona, com a passagem ainda não confirmada (azul);
  3. **atenção**, recência desatualizada (amarelo);
  4. **sem passagem confirmada**, quando a tag foi lida mas nunca teve zona
     (branco com borda);
  5. **detectado agora** (verde);
  6. **passagem confirmada** (verde-escuro).

  Os demais estados que valem para o item aparecem nos detalhes.
- **Zonas:** clicar numa zona lista os equipamentos dela. Quem só foi lido ali,
  sem confirmação, aparece como "lido aqui, ainda não confirmado".
- **Linha do tempo:** entradas e saídas, por passagem confirmada ou sem direção
  confirmada; detecção no portal aguardando confirmação; atenção; fora de
  serviço; alertas de área restrita.
- **Alertas:** o alerta de área restrita aparece em destaque, sem abrir o
  simulador.
- **O que não entra:** a posição virtual do simulador nunca entra no dashboard.

## Validação

Testes automatizados, todos no Postgres descartável local:

- `tests/test_simulacao_trajeto.py`, pelo pipeline real: motor → payload →
  ingestor → passagem → direção → zona, com relógio falso controlado. Cobre:
  - passagem completa e no sentido inverso;
  - leitura parcial, retorno e 5 s parado na fronteira, sem confirmação;
  - movimento rápido com ciclos de 0,5 s, que confirma sem pular a antena;
  - travessia em 0,15 s, ambígua pela regra `RFID_DIRECTION_AMBIGUITY_MS`, sem
    confirmação;
  - tempo ×10, com leituras no relógio simulado e transição confirmada;
  - leituras repetidas, fora de ordem e atrasadas 0,5 s, com uma única
    passagem;
  - perda de comunicação no lado A, sem passagem inventada, e reconexão com a
    passagem seguinte confirmada;
  - dois equipamentos em sentidos opostos ao mesmo tempo;
  - item novo fora das zonas, sem leitura;
  - pausa que congela o trajeto e retomada sem teletransporte;
  - avanço recusado durante trajeto e, depois, atenção pela regra de recência,
    no monitor e na API, com nova travessia aceita depois do avanço;
  - estados ao vivo: em trânsito, sem confirmação e fora de serviço com os
    detalhes preservados;
  - API de trajeto e relógio: validação, 409 e 422, relógio igual nas duas
    "pessoas" e volta a ×1 ao encerrar.
- `tests/test_location_integration.py`: passagem de tag sem associação fica
  fora da reconciliação até uma associação cobrir o instante dela.
- `frontend/src/test/Simulador.test.tsx`:
  - a tela de controle mostra só planta, zonas e itens;
  - desenhar não move nem envia nada;
  - a pausa com o botão pressionado entra no trajeto, e só soltar executa;
  - perda de captura e janela sem foco cancelam;
  - botão solto fora da janela finaliza;
  - o item em trajeto aparece no meio do caminho;
  - o item novo vai sem posição;
  - o perfil de consulta não vê os controles;
  - a interpolação é igual à do motor.
- `frontend/src/test/MapaHU.test.tsx`:
  - leitores e antenas configurados aparecem, com o pulso de leitura;
  - as cores seguem os estados do sistema, e o selo de tempo acelerado
    aparece;
  - a linha do tempo mostra as passagens;
  - a lista por zona não confirma quem só foi lido;
  - a posição virtual não aparece;
  - sem sessão, a planta de referência é mostrada.

**Não validado nesta entrega:** um ensaio com interação visível no navegador,
com duas pessoas, mouse real e o Neon/HiveMQ do modo 4. O pedido era não
abrir janelas nem tomar o foco.

## Como usar na apresentação

1. Reinicie o modo 4, `python scripts/dev.py --teste 4`. O ingestor sobe com o
   código novo: horário simulado e reconciliação sem atraso.
2. Pessoa do simulador:
   - em `#/simulador`, escolha "Hospital HUPAA (padrão)" e clique em
     **Iniciar**;
   - abra o link de controle (`#/simulador/controle/<código>`);
   - adicione equipamentos (aparecem fora das zonas);
   - pressione sobre um equipamento, desenhe o caminho e solte para executar.
3. Pessoa do dashboard: abra `#/mapa`, aba "Mapa do Hospital (HUPAA)".
4. Controles de tempo (perfil administrador, nas duas telas):
   - **Velocidade** de ×1 a ×60 acelera trajetos e relógio;
   - **+5 min, +30 min e +1 h** avançam o tempo e **não voltam atrás**. Com o
     limite padrão de 30 min, use **+30 min** e depois **+5 min** depois de uma
     passagem confirmada: o equipamento fica amarelo, em atenção.
   - O selo amarelo mostra o tempo acelerado ou adiantado.

## Limitações

- O ingestor do ensaio precisa estar com este código. Um ingestor antigo grava
  as leituras com o horário de recebimento: funciona em ×1, mas não acompanha
  o tempo acelerado.
- Leitores físicos não usam `sim_lido_em`.
- O tempo adiantado não volta atrás, de propósito. Para voltar ao tempo real,
  espere o relógio do computador alcançá-lo ou use um banco limpo.
- Com o simulador ligado (nunca em produção), a recência de **todos** os
  equipamentos usa o relógio da simulação.
- As transições impossíveis do ensaio dependem também da geometria do layout
  do HU. A antena A do portal Zona 2 ↔ Zona 3 continua no caminho
  Zona 1 → Zona 2; reposicioná-la fica a cargo de quem configura a planta.
- O monitor do dashboard é consultado a cada 1 s, e a lista de sessões a cada
  5 s. Com o Neon, cada consulta faz algumas idas ao banco remoto.
