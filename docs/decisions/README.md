# Registros de Decisões Arquiteturais (ADRs) — RFID Hospital MVP

Este diretório documenta as decisões arquiteturais fundamentais tomadas durante o projeto, motivadas por requisitos funcionais, restrições operacionais e lições aprendidas nos experimentos práticos.

---

## Índice de Decisões

| ADR | Título | Status | Contexto / Escopo |
|---|---|---|---|
| [ADR 0001](0001-local-mqtt-ingestion.md) | Ingestão MQTT local no notebook | Aceita | Definição da primeira camada local-first com Mosquitto e Paho em rede Wi-Fi controlada |
| [ADR 0002](0002-managed-mqtt.md) | HiveMQ principal e Mosquitto para desenvolvimento | Aceita | Comparação técnica HiveMQ vs. EMQX e escolha do broker gerenciado Serverless com TLS |
| [ADR 0003](0003-modelagem-dados.md) | Modelagem de dados e camada de persistência | Aceita | Adoção de PostgreSQL + SQLAlchemy + Alembic, convenções de schema e migrations |
| [ADR 0004](0004-ack-manual-persistencia-idempotente.md) | Confirmação Manual (ACK) e Persistência Idempotente | Aceita | ACK emitido estritamente pós-commit e deduplicação nativa via `event_id` canônico |
| [ADR 0005](0005-resiliencia-sem-fila-em-memoria.md) | Resiliência e Recuperação sem Fila em Memória | Aceita | Pausa de consumo, backoff exponencial e retenção durável no broker MQTT durante quedas de banco |
| [ADR 0006](0006-desacoplamento-leitor-antena-portal.md) | Desacoplamento entre Leitores, Antenas e Portais | Aceita | Remoção de `leitor.portal_id`, agregação de antenas por portais e separação de `reader_id` de serial |
| [ADR 0007](0007-unicidade-parcial-antena-ativa.md) | Unicidade Parcial de Antena Ativa e Preservação Histórica | Aceita | Índice parcial `WHERE ativo` para portas físicas de leitores e baixa lógica de hardware |
| [ADR 0008](0008-topologia-logica-versionada-portais.md) | Topologia Lógica Versionada de Portais | Aceita | Mapeamento temporal [inicio, fim), unicidade de antena ativa e separação de hardware vs. inferência |
