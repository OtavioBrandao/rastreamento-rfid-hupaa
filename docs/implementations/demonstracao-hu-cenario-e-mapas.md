# Demonstração do HU: zonas agrupadas, planta original, leitor restrito e cenário padrão

## O problema

Depois da primeira versão do "HU ao vivo"
([apresentacao-hu-trajeto-relogio-dashboard.md](apresentacao-hu-trajeto-relogio-dashboard.md)),
apareceram problemas para as apresentações (Antônio e Secomp):

- O mapa do HU usava a planta da simulação, mais pálida, e não a planta original.
- O HU tinha perdido as abas de consulta que o laboratório EASY tem.
- A lateral direita do mapa repetia informações.
- O mapa trazia controles de tempo que pertencem só ao simulador.
- Cada equipamento aparecia solto na planta. Com muitos itens, a planta fica
  ilegível.
- Faltava um cenário de demonstração que se repetisse sempre igual: seis
  equipamentos antes de iniciar, nove ao iniciar e onze depois de cadastrar
  os dois que entram durante a apresentação.

## Importância para o MVP

O dashboard é o que o hospital vê. Ele precisa ser legível e mostrar só o que o
sistema confirmou. Também precisa se comportar igual no HU e no laboratório. O
roteiro da apresentação depende de um ponto de partida previsível.

## O que foi feito

### Zonas recolhidas e expandidas (HU e EASY)

- **Recolhida:** cada zona com equipamentos mostra **um ícone com a
  quantidade** (`MapWorkspace`).
  - A cor segue a categoria com mais equipamentos na zona, usando as
    categorias e cores que o sistema já tinha (`/api/ativos`): disponível,
    atenção, offline, fora de serviço (vermelho) e nunca detectado.
  - Em caso de empate, vale a de maior prioridade de alerta: fora de serviço,
    atenção, offline, nunca detectado, disponível.
- **Expandida:** clicar no ícone mostra cada equipamento, distribuído em grade
  dentro dos limites da zona.
  - Cada marcador traz o símbolo do tipo. O nome, o estado e a última detecção
    aparecem no hover.
  - Clicar num equipamento abre o painel de detalhes, como antes.
  - Clicar de novo no ícone, clicar fora da zona ou apertar Esc recolhe.
- **Lista da zona:** a tabela "Equipamentos em …" continua aparecendo abaixo
  enquanto a zona está aberta.
- **Posição ilustrativa:** a posição dentro da zona não é física. O sistema
  sabe a zona, não a coordenada.
- **Simulador:** o simulador continua com os itens individuais, para
  acompanhar o movimento.
- O painel flutuante antigo (`ZoneCluster`) foi retirado.

### Mapa do HU (`#/mapa`, aba "Mapa do Hospital (HUPAA)")

- **Planta:** volta a ser a planta original do HU (`FloorMap`, com as cores e
  o contorno de `mapaConfig.ts`), com um pouco mais de contraste.
- **Sobreposição:** por cima da planta aparecem os **limites das zonas** do
  layout salvo (tracejado; a zona restrita em roxo) e as **posições
  aproximadas** dos leitores e antenas. As antenas pulsam com leitura gravada
  recente.
- **Ligação com o cadastro:** as zonas são ligadas aos equipamentos pelo id
  cadastrado (`zonas_ids` do layout). Por isso o mapa funciona mesmo sem
  simulação em andamento.
- **Sem layout salvo e aplicado:** o mapa mostra a planta de referência com as
  zonas do seed.
- **Abas:** as mesmas abas do EASY — Equipamentos detectados, Ativos nas salas,
  Zonas e portais, Sem zona confirmada e Outras zonas.
- **Passagens detalhadas:** uma aba nova lista quando, equipamento, portal,
  direção (confirmada, ambígua ou desconhecida) e "de → para".
- **O que saiu da tela:**
  - a lateral (entradas e saídas, sem zona no mapa);
  - os controles de velocidade e avanço do tempo, que ficam só no simulador;
  - o resumo "HU ao vivo · 4 zonas · 4 leitores".
- **Áreas de cobertura:** fica abaixo da legenda. Liga e desliga uma indicação
  aproximada do alcance das antenas, que não é medição física.
- **Fora de serviço:** o mapa passa a incluir equipamentos fora de serviço, em
  vermelho. Equipamentos com baixa lógica (inativos e sem etiqueta) não
  aparecem.

### Leitor da zona restrita

- **No editor:** ao marcar uma zona como **área restrita**, aparece "Leitor da
  zona restrita".
  - Qualquer leitor pode ser escolhido.
  - Todas as antenas dele passam a ler presença nessa zona, sem portal. Os
    outros leitores deixam de alertar.
- **Antenas:** **uma antena basta.** A segunda é opcional, e nada exige ela
  para salvar ou executar.
- **Notificação:** o backend marca o início de cada permanência na área
  restrita (`entrada_em`).
  - Uma nova entrada é a primeira leitura depois de 30 s sem leitura nela.
  - O mapa do HU mostra **uma** notificação por entrada, com o nome do
    equipamento e o horário. Enquanto o equipamento fica lá, a notificação não
    se repete; recarregar a página também não a repete.
  - Passagem confirmada para uma zona restrita também notifica, sem duplicar a
    mesma entrada.

### Cenário padrão de demonstração (`api/simulacao/cenario_demo.py`)

Vale para o layout salvo com o nome **"Hospital HUPAA (padrão)"**, que passa a
ser a configuração das apresentações. Outros layouts continuam como antes.

1. **Preparar demonstração** (botão no simulador):
   - Ficam **6 equipamentos cadastrados**, dois em cada uma das três primeiras
     zonas comuns. A zona restrita fica vazia.
   - Eles estão parados, com a última detecção mais antiga que o limite de
     recência mais 1 h 30, então aparecem **em atenção**.
   - A posição vem de correção manual justificada, registrada no histórico.
   - Nada fica em execução.
2. **Iniciar simulação** no layout padrão:
   - Os seis entram na planta dentro das suas zonas, fora do alcance das
     antenas.
   - **Três novos**, já cadastrados e sem zona, surgem no centro, junto à
     circulação central: **9 no total**.
   - Iniciar de novo, pausar e retomar não acrescentam nada.
3. **Durante a apresentação:** você acrescenta dois itens com "+ Maca" ou
   similar.
   - Eles surgem no centro com etiqueta gerada e ainda **sem vínculo** com
     cadastro.
   - Aproxime-os de uma antena e cadastre-os pela leitura: **11 no total**.
   - Nada disso é automático.
4. **Reiniciar** (na sessão do layout padrão):
   - Volta ao estado logo depois de iniciar (**9**), com o **mesmo link de
     controle**.
   - Os equipamentos da rodada anterior recebem **baixa lógica**: ficam
     inativos, sem etiqueta e com o identificador marcado `-ARQ-<data>-<id>`. Isso
     vale para os 9 e para os cadastrados a partir das etiquetas da sessão.
   - Os 9 são recriados. Nada é apagado e o histórico continua auditável.
   - Recriar, em vez de "voltar no tempo", impede que passagens antigas sejam
     reprojetadas nos equipamentos.

## Validação

- `tests/test_cenario_demo.py`:
  - 6 antes de iniciar, todos em atenção e dois por zona, com a restrita
    vazia;
  - 9 ao iniciar, com os novos sem zona, fora de toda zona e de todo alcance;
  - iniciar, pausar e retomar sem duplicar;
  - 9 + 2 cadastrados dá 11;
  - reiniciar volta a 9 no mesmo link, com baixa lógica dos 11 anteriores;
  - preparar volta a 6;
  - outros layouts continuam sem cenário.
- `tests/test_simulacao_trajeto.py`: o leitor de área restrita com uma antena
  marca uma única entrada enquanto o equipamento fica lá e uma nova depois que
  ele sai e volta (pelo pipeline real).
- `frontend/src/test/MapaHU.test.tsx`:
  - recolhe e expande a zona: o clique de novo, o clique fora e a cor da
    maioria;
  - a planta original com limites e leitores;
  - sem controles de tempo e sem o resumo antigo;
  - as cinco abas do EASY mais as passagens detalhadas;
  - a cobertura abaixo da legenda, desligada por padrão;
  - a notificação única e a nova notificação ao reentrar;
  - a zona do EASY expandida dentro da sala;
  - o desempate pela prioridade de alerta.
- `App.test.tsx` e `live.test.tsx` foram atualizados para a expansão dentro da
  zona.

Não houve ensaio visível no navegador nesta entrega.

## Dados para personalizar antes das apresentações

Em `api/simulacao/cenario_demo.py`:

- `EQUIPAMENTOS_ANTIGOS`: os seis parados, com nome, tipo e EPC.
  - Hoje são Bomba de infusão HU-01, Monitor multiparamétrico HU-02, Maca
    HU-03, Cadeira de rodas HU-04, Desfibrilador HU-05 e Ventilador pulmonar
    HU-06.
  - EPCs de `E2804C41000000000000A101` a `…A106`.
  - Os pares vão para a 1ª, 2ª e 3ª zona comum do layout.
- `EQUIPAMENTOS_NOVOS`: os três que chegam ao iniciar.
  - Hoje são Maca HU-07, Cadeira de rodas HU-08 e Bomba de infusão HU-09.
  - EPCs de `…A107` a `…A109`.
- `PREFIXO_ID` (`DEMO-HU-`): identificadores internos `DEMO-HU-01` a `09`.
- `FOLGA_ATENCAO`: o quanto a última detecção dos seis fica antes do limite de
  recência.
- Os dois itens da apresentação recebem nome e EPC na hora, no controle e no
  cadastro.

## Limitações

- O cenário usa o layout chamado exatamente "Hospital HUPAA (padrão)" e as três
  primeiras zonas comuns dele.
- As baixas lógicas se acumulam no cadastro (filtro "todos") a cada
  reinício.
- A notificação aparece no mapa do HU, não em outras páginas.
- Uma nova entrada exige 30 s sem leitura na área restrita
  (`ENTRADA_SILENCIO_S`).
