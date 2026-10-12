# Ingestor em lotes para banco remoto

## O que é

No teste com broker e banco externos (HiveMQ Cloud + Neon em `us-east-2`), as
leituras do simulador chegavam ao banco, mas o sistema não detectava passagem,
direção nem zona. No banco local o mesmo fluxo funcionava.

A causa era vazão. O ingestor tratava uma mensagem por vez e, para cada leitura,
fazia em série de 5 a 10 idas e voltas ao banco (`BEGIN`, consulta da antena,
`INSERT`, `COMMIT`, ping do pool e consultas da inferência). A ~133 ms por ida e
volta, isso dava ~0,65 leitura/s, enquanto três tags no alcance geram ~15/s. A fila
crescia sem parar e, como as leituras do EZ700 usam contador, o único horário
delas é o de recebimento: as leituras eram carimbadas com segundos de atraso e
fora de ritmo. O intervalo entre as antenas A e B passava de 3 s e o candidato a
passagem expirava.

## Importância para o MVP

O teste 3 (leitor físico com broker e banco externos) usa o mesmo caminho, com
ainda mais leituras por segundo que o simulador. Sem a correção, o sistema só
funcionaria com o banco na mesma máquina.

## O que foi feito

- **Gravação em lote** (`RawReadingRepository.persist_many`): um único `INSERT`
  de várias linhas em autocommit (atômico por ser um só comando), numa conexão
  dedicada mantida aberta, com resultado por leitura na ordem original
  (inserida, duplicada, leitor ou antena desconhecidos, inválida). A consulta
  leitor/antena fica em cache por 30 s; só resultados encontrados são guardados.
  Com o cache, cada lote custa uma ida e volta ao banco, em vez de quatro (ping
  do pool, `BEGIN`, `INSERT`, `COMMIT`).
- **Três threads no receptor** (`rfid_ingestion/mqtt_client.py`):
  - rede: lê o socket, marca o horário de recebimento, grava o JSONL e enfileira;
  - gravação: grava o lote e envia os PUBACKs logo depois do commit;
  - inferência: debounce, passagem, direção e zona, na ordem de chegada.

  Assim o horário de recebimento não espera o banco, e a inferência (várias
  consultas por passagem) não segura a janela de mensagens QoS 1 sem PUBACK do
  broker.
- **Só a thread de rede toca no socket.** Com loop manual, o paho escreve no
  socket na thread de quem chama `ack`/`disconnect`. Em TLS, escrita e leitura
  simultâneas de threads diferentes corrompem a sessão SSL: no HiveMQ Cloud a
  conexão caía em segundos. A gravação enfileira os PUBACKs e a rede os envia
  entre leituras (loop de 50 ms); desconexões pedidas por outras threads também
  passam pela rede.
- **Queda de conexão no PUBACK não é mais fatal.** `MQTT_ERR_NO_CONN` ou
  `MQTT_ERR_CONN_LOST` no envio do PUBACK só registra
  `mqtt_ack_skipped_disconnected`: o loop reconecta e o broker reentrega. Antes,
  o ingestor encerrava com `ingestor_failed` (`envio de ACK`) e o contêiner, sem
  reinício, parava de gravar.
- **Mapeamento antena/portal em cache** (`PassageRepository.resolve`): todos os
  mapeamentos da antena, inclusive históricos, ficam em cache por 30 s e os
  filtros de tempo são aplicados em memória. Sem isso, cada observação do
  debounce consultava o banco e a inferência ficava dezenas de segundos atrás.
  Sem mapeamento em cache para a observação, o banco é consultado de novo.
- **Garantia de entrega mantida**: nenhum PUBACK antes do commit. Numa falha
  temporária do banco o lote inteiro fica sem PUBACK e o broker o reentrega;
  duplicatas são descartadas pelo `event_id`. Mensagens recebidas numa sessão MQTT
  anterior nunca recebem PUBACK na conexão nova.
- **Relógio da inferência** (`MqttReceiver.relogio_inferencia`): enquanto houver
  leitura recebida e ainda não processada, o relógio do debounce e do detector de
  passagem não passa do horário de chegada dela. Sem isso, a inferência atrasada
  pelo banco tratava como silêncio leituras que já tinham chegado e apagava o
  estado da tag entre a ida e a volta.

## Validação

- Reprodução com o ingestor real, Mosquitto e PostgreSQL descartáveis e latência
  artificial por comando SQL: uma tag parada na antena A lendo sem parar, a tag X
  indo de A para B e voltando, e a tag Y indo de A para B ao mesmo tempo que X
  volta.
  - Código anterior, 133 ms: 74 de 140 leituras gravadas na janela do ensaio e
    nenhuma passagem.
  - Código novo, 133 ms (três rodadas) e 250 ms (duas rodadas): 140 de 140
    leituras, X `a_para_b` e `b_para_a` com Zona B e Zona A, Y `a_para_b` com
    Zona B, nenhuma direção ambígua e nenhuma passagem da tag parada.
- Ambiente real (HiveMQ Cloud + Neon `us-east-2`), ingestor no host com o
  `.env.cloud` e o publicador com a credencial `reader-01`:
  - mesmo cenário das três tags, duas rodadas: X `a_para_b` e `b_para_a` com Zona
    B e Zona A, Y `a_para_b` com Zona B, nenhuma ambiguidade nem queda;
  - 3 minutos com duas tags lendo sem parar (~10 leituras/s): 1798 de 1798
    leituras no Neon, ritmo constante, nenhuma queda.
  - Antes da correção do socket, a conexão TLS caía em ~8 s e o ingestor
    encerrava.
- Testes novos para o lote no repositório (ordem, duplicata no lote, rejeições,
  uma transação, cache e TTL) e no receptor (ACK depois do commit e antes da
  inferência, nenhum ACK com o banco indisponível, sessão anterior sem ACK,
  thread de gravação e relógio da inferência). Suíte completa e integração com
  Mosquitto real (`RUN_MQTT_INTEGRATION=1`) passando.

## Limites

- A latência continua atrasando o que aparece no dashboard: no ambiente real, a
  zona foi gravada de 6 a 13 s depois da passagem. A interpretação não muda.
- O QoS 1 faz o broker entregar em rajadas a cada ~0,5 s (ciclo commit → PUBACK).
  As leituras de uma mesma rajada recebem quase o mesmo horário; uma travessia
  mais rápida que isso entre as antenas pode ficar com direção ambígua.
- Alterações de mapeamento antena/portal valem em até 30 s para a inferência.
- Depois de uma queda longa, o HiveMQ Cloud guarda um número limitado de
  mensagens na sessão do ingestor e descarta o excedente.
- Um banco na região de São Paulo reduziria esse atraso; não é necessário para
  a lógica funcionar.
