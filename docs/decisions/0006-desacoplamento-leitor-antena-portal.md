# ADR 0006 — Desacoplamento entre Leitores, Antenas e Portais

## Status
Aceito e implementado (ISS-012)

## Contexto
Na concepção inicial do schema (ISS-002a), existia a coluna `leitores.portal_id`, assumindo-se que cada leitor RFID pertencia a um único portal físico de monitoramento.

Entretanto, durante o refinamento da topologia de hardware para o HUPAA:
1. **Passagens com Múltiplos Leitores:** Em corredores amplos ou portais duplos, é comum posicionar um leitor físico em cada batente da porta ou em posições opostas, com antenas apontando para a mesma passagem. Vincular o portal ao leitor impedia que um portal agregasse antenas conectadas a leitores físicos diferentes.
2. **Antenas Avulsas:** Existem cenários de leitura por presença (ex.: mesa de triagem, teto de sala ou ponto de checagem) onde não há portal entre duas zonas. A modelagem anterior forçava a criação de um portal artificial.
3. **Identidade Lógica vs. Física do Leitor:** O leitor possui um número de série de fábrica (`identificador_serial`), mas no MQTT ele é identificado pelo segmento do tópico (`reader_id`, ex.: `reader-01`), que pode ser reorganizado ou reatribuído sem alterar o hardware físico.

## Decisão
1. **Eliminar `leitores.portal_id`:** O relacionamento direto entre leitor e portal foi removido na migration `019782a38ff7`.
2. **Antena como Elo de Agregação:**
   - A antena física pertence de forma imutável a um leitor: `antenas.leitor_id` (`NOT NULL`).
   - A antena associa-se opcionalmente a um portal: `antenas.portal_id` (`NULLABLE`, editável).
   - Um portal agrega logicamente todas as antenas que apontam para as zonas que ele delimita (`antenas.portal_id = portal.id`).
3. **Separação Estrita de Identificadores:**
   - `leitores.reader_id`: `VARCHAR`, `NOT NULL`, `UNIQUE` — identificador lógico da origem no tópico MQTT.
   - `leitores.identificador_serial`: `VARCHAR`, `NOT NULL`, `UNIQUE` — número de série de fábrica do equipamento.

## Consequências
- Total flexibilidade para compor portais físicos com antenas de um ou múltiplos leitores.
- Suporte nativo a antenas de inventário pontual que não delimitam transição entre zonas (`portal_id IS NULL`).
- A ingestão resolve `(reader_id, porta_numero) -> antena_id` sem precisar conhecer o portal antecipadamente.
