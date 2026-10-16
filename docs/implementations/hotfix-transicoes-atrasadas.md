# Transições atrasadas ou perdidas no simulador

## O que é

No simulador visual com broker e banco externos (HiveMQ Cloud + Neon), a troca
de um equipamento entre as antenas A e B demorava a aparecer no painel e, para
alguns equipamentos, não era detectada. As leituras chegavam ao banco
normalmente. O problema estava entre a recepção e a projeção da zona.

Em 18 minutos de ensaio, o ingestor registrou **11 passagens**. **Cinco** ficaram
com direção `ambiguous` (regra `temporal_proximity_v1`) e não atualizaram a
zona. Um dos equipamentos teve três passagens seguidas descartadas assim.

## Importância para o MVP

A última zona confirmada é o resultado principal do sistema. Uma passagem
física que termina em `ambiguous` ou some antes de virar passagem deixa o
equipamento com a zona antiga, e o operador não tem como saber que houve
movimento. O mesmo caminho será usado pelo leitor físico no teste com broker e
banco externos.

## Causas encontradas

### 1. Monitor de leitores segurando o PUBACK

O `ReaderMonitor` (status por contato dos leitores) gravava o contato do leitor
**a cada lote, antes do PUBACK**, numa transação com `SELECT … FOR UPDATE`.
Além disso, o sweep de 1 s rodava na mesma thread de gravação. Medido no
ambiente externo:

| Medida | Valor |
|---|---|
| Ida e volta ao banco | ~136 ms |
| Transação do monitor | ~550 ms |
| Ciclo lote → PUBACK → próxima entrega | ~1,4 s |

Com QoS 1, o broker só entrega mais mensagens depois dos PUBACKs. As leituras
chegavam em **rajadas de ~25 a cada 1,4 s**. Um assinante QoS 0 de diagnóstico
recebia as mesmas mensagens em ritmo regular (~140–200 ms). Como o horário da
leitura do EZ700 é o horário de recebimento, a última leitura em A e a primeira
em B ficavam a **~30 ms** uma da outra dentro da mesma rajada. Abaixo dos 100 ms
de `RFID_DIRECTION_AMBIGUITY_MS`, a direção virava `ambiguous`, sem zona.

### 2. Observação de destino só fechava ao sair do alcance

O debounce só finalizava uma observação após silêncio (`janela + tolerância`).
Com a tag parada na antena de destino, uma leitura a cada 200 ms (menor que a
janela de 250 ms) mantinha a observação aberta. A passagem só era proposta
quando o item **saía** de B. Se ficasse em B mais que ~4 s, o detector
apagava o candidato de A por silêncio, e a passagem **se perdia**.

Replay em memória com chegadas regulares:

| Permanência em B | Antes | Depois |
|---|---|---|
| 1,5 s | detectada 2,95 s após entrar em B | igual (observação curta fecha por silêncio) |
| 3 s | 4,35 s | 1,85 s |
| 5, 10 e 30 s | **perdida** | 1,85 s |

As rajadas da causa 1 escondiam a causa 2: cada intervalo entre rajadas
partia a observação. Corrigir só a primeira tornaria a segunda mais frequente.

## O que foi feito

- **Contatos de leitura fora do PUBACK** (`rfid_ingestion/reader_status.py`,
  `rfid_ingestion/mqtt_client.py`):
  - heartbeats continuam gravados antes do PUBACK, como na ISS-024;
  - contatos de leitura vão para `ReaderMonitor.defer`, um buffer em memória
    com o contato mais recente de cada leitor;
  - o sweep grava esse buffer no máximo uma vez por segundo, numa thread
    própria (`rfid-reader-monitor-…`), sem atrasar lote nem PUBACK;
  - se o banco falhar no sweep, os contatos voltam ao buffer e a recuperação
    segue o fluxo existente (`database_unavailable`).
- **Duração máxima da observação** (`rfid_inference/debounce.py`): o novo
  parâmetro `max_observation` (`RFID_DEBOUNCE_MAX_OBSERVATION_MS`, padrão
  500 ms; `0` desativa) finaliza a parte já estável (até o watermark) de uma
  observação que continua recebendo leituras. A continuação segue como nova
  observação e não é tratada como tardia.
  - Do mesmo lado, essas observações parciais só renovam o candidato ou a âncora.
  - A verificação de origem ativa/reflexão continua igual: a tag parada na
    sobreposição das duas antenas segue sem gerar passagem.
- **Silêncio do detector de passagem** (`rfid_ingestion/__main__.py`): a folga
  passa a incluir a duração máxima da observação, já que a primeira observação
  de destino chega até esse tempo depois.
- Configuração nova em `rfid_ingestion/config.py`, `deploy/compose.yaml`, nos
  `.env*.example` e em `docs/architecture/system-overview.md`.

## Validação

- Testes novos:
  - `tests/test_debounce.py`: corte de leitura contínua sem eventos tardios e sem
    perder leituras, limite desativado com `0` e valor inválido;
  - `tests/test_passage.py`: tag parada 3, 10 e 30 s no destino confirma
    A→B em menos de 2,5 s;
  - `tests/test_reader_status.py`: lote de leituras envia PUBACK sem gravar o
    monitor; o sweep grava o buffer, respeita 1 s e o mantém após falha.
- Suíte completa com PostgreSQL descartável: 1361 testes aprovados (2 pulados).
  Ruff e verificação de docstrings sem apontamentos.
- Ambiente externo (HiveMQ Cloud + Neon), ingestor `ingestor-managed`
  reconstruído:
  - rajadas passaram de ~25 leituras/1,4 s para ~8 leituras/0,47 s, com o
    simulador publicando ~18 leituras/s;
  - quatro trocas roteirizadas com o `Publicador` do simulador e um equipamento
    sintético (A→B, B→A, A→B, B→A), ficando 6–8 s parado no destino: **4 de 4**
    passagens `confirmed`, direção correta e zona atualizada. Intervalo entre
    evidências de 457 a 930 ms, nenhuma `ambiguous`. A passagem foi confirmada
    ~2–3 s após a entrada no destino e a zona gravada ~4 s depois.

## Segunda etapa: nenhuma transição sem detecção

Requisito do MVP: se a tag foi lida num lado do portal e depois no outro, a
transição **tem** de virar passagem com direção confirmada. Mesmo após a
primeira etapa, ainda havia três caminhos de perda:

| Caso | Antes | Agora |
|---|---|---|
| Troca rápida: últimas leituras de A e primeiras de B na mesma rajada (~30 ms) | `ambiguous`, sem zona | `confirmed`, regra `arrival_order_v1` |
| Troca lenta: mais de 3 s entre sair de A e entrar em B, ou item levado ao destino sem passar pelo alcance da outra antena | candidato expirava, sem passagem | passagem confirmada |
| Ingestor reiniciado com a tag de um lado | primeira observação do outro lado sem par | último lado recuperado do banco |

- **Ordem de chegada** (`rfid_inference/direction.py`,
  `direction_repository.py`):
  - o horário das leituras com contador é o de recebimento, e numa rajada QoS 1
    leituras de antenas diferentes chegam a poucos milissegundos;
  - a ordem de publicação de um mesmo leitor é preservada pelo MQTT e pela
    sequência de gravação (IDs crescentes);
  - dentro de `RFID_DIRECTION_AMBIGUITY_MS`, evidências do **mesmo leitor**
    passam a ser ordenadas pelo ID da leitura (`arrival_order_v1`). Leitores
    diferentes continuam `ambiguous`.
- **Sem limite entre os lados** (`rfid_inference/passage.py`):
  `RFID_PASSAGE_MAX_INTERVAL_MS` aceita `0`, agora o padrão, e o detector
  não expira o último lado de cada tag. Um valor positivo restaura o
  comportamento anterior da ISS-015.
- **Estado recuperado após reinício** (`passage_repository.previous_observation`,
  `passage_service`): na primeira observação de um EPC sem estado em
  memória, a última leitura dele no mesmo portal vira o candidato de origem.
- Continuam valendo:
  - a proteção contra reflexão (origem ainda lendo a tag durante o destino);
  - o período refratário de 1 s logo após uma passagem. Com as observações
    parciais, a tag que permanece no outro lado gera nova passagem assim que o
    refratário termina.

Validação: testes de direção (mesmo leitor a 0, 29 e 100 ms confirma; leitores
diferentes seguem ambíguos), detector sem limite (travessia após 2 min,
estado mantido por 1 h), restauração no serviço e integração com PostgreSQL
(reinício + evidências a 20 ms ⇒ `confirmed`, `arrival_order_v1`, zona de
destino). Suíte completa: 1368 aprovados, 2 pulados.

## Limites

- Com banco externo, ainda há rajadas a cada ~0,5 s (lote e PUBACK). A
  direção é resolvida pela ordem de chegada; só antenas de leitores
  diferentes no mesmo portal continuam sujeitas a `ambiguous`.
- Sem limite de tempo, uma leitura espúria da antena do outro lado (fora da
  janela de reflexão) gera passagem. Isso precisa de validação física com o
  EZ700 antes de uso no hospital.
- Entre passagem confirmada e zona gravada ficam ~4 s de consultas de direção e
  projeção no banco remoto. Não foi alterado aqui.
- O contato de leitura do leitor é gravado com até ~1 s de atraso. Os limites
  de status (30 s e 90 s) não são afetados.
- `RFID_DEBOUNCE_MAX_OBSERVATION_MS` é configuração de software e ainda precisa
  de validação física com o Identix EZ700.
