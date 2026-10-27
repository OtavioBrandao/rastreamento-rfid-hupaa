# Portal de entrada da zona e itens sobrepostos (teste local de 26/10/2026)

## O problema

No teste local (modo 1), apareceram duas falhas:

1. **Entrada na Zona 1 não confirmada.** A Cadeira de rodas HU-08 foi levada à
   entrada da Zona 1 e lida pelas duas antenas do Leitor 1, nas duas ordens. O
   sistema mostrou só a aproximação e manteve a localização anterior ("Outro
   andar (elevador)").
2. **Passagem "falsa" da Maca HU-07.** As passagens detalhadas mostraram a maca
   saindo da Zona 2 e entrando na Zona 3 pelo portal, embora ela não tivesse
   sido movida de propósito.

## Importância para o MVP

A apresentação depende de a zona ser confirmada quando o equipamento entra
nela, e só nessa hora. Uma entrada que não confirma e uma passagem que ninguém
pediu tiram a confiança na lógica que se quer mostrar.

## Investigação (banco local, somente leitura)

### Falha 1: Cadeira HU-08 (tag `…A108`)

**Leituras gravadas** (horários em UTC, 27/10/2026), por antena:

| Antena | Horário | Leituras |
|---|---|---|
| 3 (Leitor 1, porta 1) | 01:03:23–01:04:02 | 152 |
| 4 (Leitor 1, porta 2) | 01:04:05 | 1 |
| 4 | 01:04:59–01:05:22 | 108 |
| 3 | 01:05:23–01:05:24 | 6 |
| 3 | 01:05:35–01:05:40 | 15 |
| 4 | 01:05:41–01:05:42 | 5 |
| 4 | 01:05:50 | 4 |
| 3 | 01:05:51–01:12:51 | 1799 |

**Mapeamentos em vigor:**

- A antena 3 era o **lado A do portal "Zona 1 ↔ Zona 2"**. O lado B desse
  portal era a antena 5, do **Leitor 2**.
- A antena 4 **não pertencia a nenhum portal**.

**Causa:**

- Leituras de antena sem portal não entram na detecção de passagem.
- O portal da antena 3 só fecharia com uma leitura no Leitor 2, que não
  aconteceu.
- Nenhuma passagem foi gravada para a `…A108`.

Não houve perda, deduplicação nem desordem: todas as leituras foram gravadas e
correlacionadas por tag e antena. Faltava a regra pedida: **um leitor com duas
antenas na entrada da zona é o portal dela**, e as duas antenas lendo, em
qualquer ordem, confirmam a zona.

Mesmo com as duas antenas no mesmo portal, a regra antiga, direcional,
falharia neste caso. Com as antenas lendo juntas na porta, a regra "origem
ainda ativa" descarta a passagem como reflexo, e a ordem B → A levaria o
destino para fora da zona. O teste de regressão com o modo direcional
reproduz isso: a cadeira continua na Zona 2.

### Falha 2: Maca HU-07 (tag `…A107`)

**Leituras e passagem:**

- 2 leituras na antena 7 (Leitor 3, lado Zona 2), às 01:03:28,3–30,2.
- 6 leituras na antena 8 (Leitor 3, lado Zona 3), às 01:03:30,5–31,4.
- A passagem 2, "Zona 2 → Zona 3", foi confirmada pela regra
  `temporal_side_order_v1`.

**Como o sistema chegou lá:**

- O log da API mostra, às 01:03:26,
  `POST /api/simulacao/sessoes/e01451f8071a5e56/itens/demo-07/trajeto`: um
  trajeto **executado na Maca HU-07**, do centro (50; 50) até (20,8; 94,3).
  Os trajetos imediatamente antes e depois foram da Cadeira HU-08 (`demo-08`).
- A maca surgiu em (50,0; 50,0) e a cadeira em (50,0; 53,0). São 3 unidades de
  altura da planta, cerca de 16 px na tela, para marcadores de 24 px: **os
  ícones ficaram sobrepostos**.

**Conclusão:** o sistema confirmou um movimento que de fato foi executado. O
clique, porém, atingiu o item errado. Isso é inferido do log, porque o clique em
si não é registrado.

## O que foi feito

- **Portal de entrada da zona.** A coluna nova `portais.modo` (migration
  `s041a1b2c3d4`) aceita dois valores:
  - `direcional` é o padrão e o comportamento anterior: a ordem A → B ou B → A
    decide o destino. O EASY e os portais entre duas zonas não mudaram.
  - `entrada` é o leitor com pelo menos duas antenas na entrada da zona B, com
    a 1ª antena do lado de fora (circulação). As duas antenas lendo, em
    **qualquer ordem**, confirmam a zona B, pela regra
    `entry_portal_any_order_v1`. A verificação de "origem ainda ativa" não vale
    nesse modo: as duas antenas lerem juntas na porta é a própria evidência.
  - Uma leitura isolada continua sendo só aproximação ("visto perto"), sem
    confirmar a zona.
- **Editor do simulador.**
  - No leitor, "Portal da zona (leitor com 2+ antenas)" transforma o leitor no
    "Portal para Zona N".
  - O lado de fora usa a zona "Circulação (fora das zonas)", que não precisa de
    área.
- **Layout local do HU** (cópia antes em `data/backups/layout-hu-local-v1-*.json`):
  - Leitor 1 → Portal para Zona 1; Leitor 2 → Portal para Zona 2; Leitor 3 →
    Portal para Zona 3. A Antena 1 de cada um fica do lado de fora.
  - O antigo "Zona 1 ↔ Zona 2" saiu, porque as antenas dele são agora as
    entradas das duas zonas.
  - O Leitor 4 continua sendo o portal de zona restrita (presença).
- **Itens novos afastados.** Os itens passam a surgir a pelo menos 4 unidades
  de largura uns dos outros, medidas na escala real da tela
  (`distancia_na_tela`), em vez de 3 unidades sem escala. Isso vale para o
  surgimento no centro e para o cenário de demonstração.

## Validação

- `tests/test_portal_entrada.py`, pelo pipeline real (motor → MQTT → ingestor
  → passagem → direção → zona), com antenas sobrepostas como no teste local:
  - o portal fica gravado com `modo = entrada`;
  - Antena 1 → 2 confirma a Zona 1;
  - Antena 2 → 1 também confirma a Zona 1;
  - leitura só da Antena 1, ida e volta, não confirma nada;
  - o portal direcional continua igual (B → A vai para A), e o mesmo contexto
    no modo entrada vai para B;
  - itens novos surgem a pelo menos 4 unidades na tela, e o trajeto de um item
    não gera leitura nem passagem no outro.
  - Com o portal no modo direcional, os dois testes de passagem **falham**:
    a cadeira continua na Zona 2. Isso reproduz a falha 1.
- `frontend/src/test/Simulador.test.tsx`: o atalho "Portal da zona" põe a 1ª
  antena fora e a 2ª dentro, sem pendência de área.
- **Ensaio local de ponta a ponta** (API, Mosquitto e ingestor locais, com a
  imagem reconstruída):
  - **Cadeira HU-08**, do centro para dentro da Zona 1: 7 leituras na
    Antena 1 do Leitor 1 e 7 na Antena 2. A passagem "Portal para Zona 1" foi
    confirmada pela `entry_portal_any_order_v1`, e a zona ficou **Zona 1**.
  - **Maca HU-07**, que só encostou na Antena 1 e voltou: 7 leituras só nela,
    nenhuma passagem, e a zona continuou "Outro andar (elevador)".
  - Nenhum outro item foi lido.

## Limitações

- Para usar o modo novo no Neon, é preciso aplicar a migration `s041a1b2c3d4`
  e reconfigurar o layout de lá, com o atalho do editor.
- No modo entrada, sair da zona pelo mesmo portal também confirma a zona: a
  regra pedida é "qualquer ordem". A saída aparece quando o equipamento entra
  em outra zona.
