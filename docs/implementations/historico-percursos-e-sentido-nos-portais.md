# Sentido nos portais de entrada, histórico em percursos e ajustes da demonstração (27/10/2026)

## O problema

1. **Histórico vazio e errado no painel do equipamento.** A seção "Histórico de
   movimentações" ficava vazia até clicar em "Ver histórico completo". Na Maca HU-07
   ela mostrava `Circulação (fora das zonas) → Zona 1`, `Circulação → Zona 2` e
   `Circulação → Zona 3` em sequência, sem nenhuma saída. A causa estava na
   inferência, não na tela. A regra `entry_portal_any_order_v1` (de 26/10) tratava
   qualquer ordem das antenas como entrada, então sair de uma zona também virava
   "entrada".
2. **Indicador verde curto demais.** O ponto verde de "leitura recente" durava 30 s.
3. **Mapa do HU.** Faltava uma planta mais limpa para a apresentação. O nome
   "Circulação vertical (escada)" cobria o corredor.
4. **Cenário local acumulando cadastros.** Cada preparo deixava cópias `-ARQ-`:
   eram 9 equipamentos na visão normal e 37 com os inativos.

## Importância para o MVP

A demonstração mostra *por onde* o equipamento passou. Se uma saída aparece como
entrada, ou se as setas não refletem o deslocamento real, a lógica perde a
credibilidade. O histórico precisa contar o percurso real (origem → destino) com as
evidências que o confirmam, e o cenário precisa começar sempre do mesmo ponto.

## O que foi feito

### 1. Sentido nos portais de entrada (inferência)

Em cada portal de entrada do HUPAA, a **Antena 1** fica na circulação (lado A) e a
**Antena 2** fica dentro da zona (lado B).

| Leituras | Resultado |
|---|---|
| Antena 1 → Antena 2 | `Circulação → Zona X` (entrou) |
| Antena 2 → Antena 1 | `Zona X → Circulação` (saiu); se parar, continua na circulação |
| Só a Antena 1 | "Visto perto da Zona X" (observação, sem deslocamento) |
| Leituras repetidas da mesma antena | nada novo |
| Parado na porta, lido pelas duas antenas | nada, enquanto não houver leitura isolada do outro lado |

- **Regra de sentido.** `entry_portal_any_order_v1` foi substituída por
  `entry_portal_order_v1`, que é a mesma inferência por ordem dos portais
  direcionais, só com outro nome de regra. A esquerda da seta é sempre a origem
  real.
- **Portal de entrada sem atalho.** `origin_active` não ignora mais o portal de
  entrada.
- **Sobreposição na porta** (`rfid_inference/passage.py`). O leitor multiplexa as
  portas: parada na porta, a tag é lida pelas antenas alternadamente, a cada
  0,1 s, em pedaços de observação de 0,5 s. Por isso a passagem agora é
  **provisória**:
  - **Confirmação.** Ela só é proposta quando o destino segue lido pela janela de
    confirmação sem a origem voltar. A janela é retenção + tolerância de
    sobreposição + atraso do debounce, cerca de 2 s. A passagem também é proposta
    quando esse tempo passa sem nada novo, ou no encerramento.
  - **Descarte.** Se a origem volta a ler junto com o destino, a passagem
    provisória é descartada.
  - **Volta rápida.** Se o destino parou antes de a origem voltar, a travessia
    valeu e a nova leitura já é a volta.
  - **Conferência nas leituras gravadas** (`PassageRepository.exclusive_crossing`).
    Na confirmação, a passagem exige uma leitura **isolada** da origem seguida de
    uma isolada do destino. Isolada quer dizer sem leitura da outra antena a menos
    de 0,3 s. A evidência gravada passa a ser exatamente essas duas leituras.
- **Evidência de outra rodada.** Uma passagem só vira movimentação se a **leitura
  de origem** também for do vínculo atual da etiqueta (`rfid_movement/service.py`
  e `rfid_location/repository.py`). Depois de reiniciar a demonstração, o ingestor
  pode lembrar a última antena da rodada anterior; esse par não gera mais uma
  saída falsa.

### 2. Histórico em percursos (API e painel)

- **Rota nova** `GET /equipamentos/{id}/percursos` (`api/service_percursos.py`).
  A "circulação" é o lado A dos portais de entrada. A rota junta as etapas
  confirmadas em acontecimentos:
  - **Percurso:** `Zona 1 → Zona 2`, com as etapas `Zona 1 → Circulação` e
    `Circulação → Zona 2`. Enquanto só a saída está confirmada, o percurso fica
    incompleto (`Zona 1 → Circulação`).
    - Se a entrada não tem saída registrada, a origem é a última localização
      confirmada (ex.: `Outro andar (elevador) → Zona 1`).
    - Sem localização anterior, aparece **"Origem desconhecida"**.
  - **Correção manual:** acontecimento próprio, com justificativa e referência.
  - **Observação:** "Visto perto da Zona X". Na Antena 1 de um portal de entrada,
    a zona de referência é a do portal, não a circulação. A leitura que é
    evidência de uma etapa confirmada não aparece repetida.
- **Detalhes de cada etapa:** portal, leitor, antenas na ordem lida (`2 → 1`), data
  e hora das duas leituras usadas como evidência e duração da travessia. O
  percurso traz também o tempo na circulação entre as etapas. Tudo vem de
  registros gravados; nada é estimado.
- **Última observação separada.** `ultima_observacao` (última leitura em qualquer
  antena) fica separada da última localização confirmada.
- **Painel do equipamento.**
  - Ao abrir, mostra até **três acontecimentos** com data e hora (fuso de Maceió).
    Cada linha traz o rótulo "Percurso concluído", "Saída confirmada · parado na
    circulação" ou "Observação" com "entrada não confirmada".
  - "Ver histórico completo" mostra cada deslocamento em um bloco com as etapas e
    as evidências.
  - A linha "Última observação perto de uma antena" foi acrescentada.
  - Tudo é atualizado ao vivo e continua correto depois de recarregar.

### 3. Indicador de leitura recente

`PRESENCE_FRESH_MS` passou de 30 s para **90 s**.

- **Verde:** até 90 s desde a última leitura em qualquer antena; cada leitura nova
  recomeça a contagem.
- **Depois:** cinza, com "Sem leitura recente".
- **Onde vale:** no painel, no inventário e na tabela de detectados. A janela de
  5 min das listas, a inferência e os alertas não mudaram.

### 4. Mapa simplificado e nomes reposicionáveis

- **Alternância de planta.** Junto da legenda há o controle "Planta colorida /
  Planta simplificada".
  - No modo simplificado, o corredor fica preto, a área verde (circulação vertical)
    fica cinza e as demais ficam brancas.
  - A legenda de cores da planta some. Limites, leitores, antenas, equipamentos e a
    legenda de status continuam.
  - A preferência fica no navegador: é só visual.
- **Nomes de zona arrastáveis.** A posição é gravada no layout compartilhado pela
  rota `PUT /api/simulacao/layouts/{id}/zonas/{chave}/rotulo`, no campo
  `zonas[].rotulo`.
  - Arrastar não muda a área nem dispara o clique que expande a zona. O clique
    simples continua expandindo.
  - A versão do layout sobe, para um editor aberto não sobrescrever a posição.

### 5. Limpeza do cenário local

No **banco local** (`localhost`/`127.0.0.1`, fora de produção), "Preparar
demonstração" e "Reiniciar" **excluem de vez** todos os cadastros de equipamento,
com vínculos, histórico e etiquetas sem uso. Isso inclui os ensaios arquivados
antigos e os itens acrescentados na rodada. Depois:

- **Preparar:** 6 equipamentos, dois por zona.
- **Iniciar ou reiniciar:** 9 equipamentos, dois por zona e três no centro.

Usuários, layouts, zonas, leitores e leituras brutas ficam. Em qualquer outro
banco (ex.: Neon), continua a baixa lógica (`-ARQ-`), e nada é apagado.

## Validação

- **`tests/test_percurso_entrada.py`:** pipeline real (motor → MQTT → ingestor →
  passagem → direção → localização) com o **layout local da demonstração**
  (`tests/fixtures/layout_hu_demo_entradas.json`) e o **detector configurado como
  no ingestor real**. Cobre:
  - saída `Zona 1 → Circulação`, parada sem nada mudar, entrada na Zona 2
    (percurso `Zona 1 → Zona 2` com as duas etapas, ordens `2 → 1` e `1 → 2` e
    tempo na circulação) e volta `Zona 2 → Zona 1`;
  - 20 s parado no alcance de uma antena: nenhuma movimentação;
  - elevador: só a Antena 1 lê, a observação "Visto perto da Zona 1" aparece e a
    localização continua "Outro andar"; depois a passagem 1 → 2 dá
    `Outro andar (elevador) → Zona 1`;
  - sem origem conhecida: `Origem desconhecida → Zona 1`;
  - reinício sem saída falsa, e uma passagem com leitura anterior ao vínculo que
    não vira movimentação nem volta ao reprocessamento.
- **`tests/test_portal_entrada.py`:** alcances sobrepostos. Cobre `1 → 2` entra e
  `2 → 1` sai para a circulação; parada na porta e volta para fora sem passagem;
  parada na porta e entrada com uma entrada só; e a regra nos dois modos.
- **`tests/test_cenario_demo.py`:** 6/9 equipamentos, nenhum `-ARQ-` nem extra
  depois do reinício e dois por zona; e a baixa lógica fora do banco local.
- **Frontend** (`Historico.test.tsx`, `MapaHU.test.tsx` e testes existentes
  ajustados):
  - resumo de três acontecimentos e blocos com etapas e evidências;
  - verde até 89 s e cinza aos 91 s;
  - os dois modos do mapa;
  - arrastar o nome grava no layout sem expandir a zona.

## Limitações

- **Atraso da confirmação.** A passagem é confirmada cerca de 2 s depois da
  travessia (janela de confirmação). Parado na porta, nada é confirmado até a tag
  ser lida sozinha de um dos lados.
- **Relógio do verde.** O verde é calculado no relógio do navegador, como a idade
  das leituras. Com o tempo da simulação adiantado ("Avançar tempo"), as leituras
  ficam com horário futuro e o indicador não reflete esse avanço.
- **Duas antenas por lado.** A conferência de leituras isoladas usa as duas antenas
  da passagem (uma por lado), como nos portais da demonstração.
- **Entrada na Zona 3 perdida no teste local de 27/10 (diagnóstico, ainda sem
  correção).** O caso foi a Bomba de infusão HU-09, às 04:29 UTC.
  - **Leituras:** Antena 1 (circulação) de 04:29:19,7 a 04:29:20,8 e Antena 2
    (dentro) a partir de 04:29:21,0. A entrada `Circulação → Zona 3` não foi
    registrada; só às 04:30:44 vieram uma "saída" e uma nova entrada.
  - **Primeira causa: estado da rodada anterior.** O ingestor tinha acabado de
    reiniciar e restaurou o último lado da etiqueta nesse portal a partir do banco
    (`rfid_passage_state_restored`, lado B). Essa leitura era de 01:54:47, da rodada
    anterior da demonstração, antes do vínculo atual da etiqueta (04:23:48). Para o
    detector, a bomba já estava dentro da Zona 3, e a passagem pela Antena 1 virou
    uma "saída" provisória.
  - **Segunda causa: tolerância de sobreposição.** A Antena 2 começou 0,19 s depois
    da última leitura da Antena 1, dentro da tolerância de 0,3 s. Por isso a volta
    à Antena 2 foi tratada como "as duas antenas lendo juntas", e não como travessia
    (`rfid_passage_tentative_discarded`).
  - **Resultado:** a entrada real foi descartada.
  - **Correção possível, não aplicada:** a restauração do estado
    (`PassageRepository.previous_observation`) deveria ignorar leituras anteriores
    ao vínculo atual da etiqueta, ou de outra rodada.
