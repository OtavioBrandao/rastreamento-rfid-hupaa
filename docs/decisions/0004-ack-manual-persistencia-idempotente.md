# ADR 0004 — Confirmação Manual (ACK) e Persistência Idempotente via Chave Canônica

## Status
Aceito e implementado (ISS-005, ISS-006)

## Contexto
O protocolo MQTT opera em nível QoS 1 (*at-least-once*), o que significa que o broker garante a entrega da mensagem, mas retransmissões automáticas podem ocorrer caso a confirmação (`PUBACK`) se perca na rede ou ocorra uma reconexão de cliente.

No pipeline anterior (ISS-001):
1. O receptor MQTT operava com confirmação automática antes de qualquer persistência durável.
2. Não havia garantia de que falhas transitórias do banco de dados não resultassem em perda definitiva da mensagem.
3. Se uma mensagem retransmitida pelo broker fosse inserida cegamente no banco de dados, causaria duplicações espúrias de leituras para a mesma passagem física, falseando relatórios e contagens.

## Decisão
1. **Confirmação Manual (`manual_ack`):** Configurar o cliente Paho MQTT com `manual_ack_set(True)`. O envio do ACK ao broker ocorre estritamente **após** a persistência bem-sucedida da transação no PostgreSQL ou após uma rejeição definitiva auditada (ex.: payload inválido ou leitor inexistente).
2. **Chave Canônica Determinística (`event_id`):** O `event_id` é computado como o hash SHA-256 em formato string `sha256:<64 hex>` derivado exclusivamente do tópico MQTT, do payload binário bruto e de parâmetros contextuais. Ele independe de relógios de recepção e de identificadores efêmeros de transporte.
3. **Idempotência no PostgreSQL:** A inserção na tabela `leituras_brutas` utiliza a cláusula atômica:
   ```sql
   INSERT INTO leituras_brutas (event_id, antena_id, epc, rssi, dados_origem, lido_em, recebido_em)
   VALUES (:event_id, :antena_id, :epc, :rssi, :dados_origem, :lido_em, :recebido_em)
   ON CONFLICT (event_id) DO NOTHING
   RETURNING id;
   ```
   Se `RETURNING id` retornar uma linha, a leitura foi inserida (`inserted`). Se retornar vazio, tratou-se de uma duplicata idempotente (`duplicate`). Em ambos os casos, a transação realiza `commit` e o ACK manual é emitido.

## Consequências
- Reentregas do broker nunca geram linhas redundantes em `leituras_brutas`.
- Falhas temporárias no PostgreSQL impedem a emissão do ACK, mantendo a mensagem na fila do broker para reentrega segura.
- O arquivo append-only de auditoria (`raw_events.jsonl`) continua registrando cada tentativa de entrega observada pela rede, permitindo distinguir retransmissões de rede de eventos únicos.
