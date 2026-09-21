# ADR 0005 — Resiliência e Recuperação sem Fila em Memória

## Status
Aceito e implementado (ISS-007)

## Contexto
Em ambientes assistenciais hospitalares, falhas temporárias de banco de dados (reinicialização de contêineres, oscilações de rede com o Neon Cloud ou manutenção preventiva) ocorrem de forma imprevisível.

Uma abordagem comum seria enfileirar mensagens em memória (ex.: `asyncio.Queue` ou buffer interno em Python) enquanto o banco estivesse inacessível. No entanto:
- Quedas prolongadas levariam a esgotamento de memória (*Out of Memory* — OOM) do processo.
- Se o ingestor sofresse uma reinicialização ou crash durante a queda do banco, todas as mensagens retidas no buffer volátil em memória seriam perdidas permanentemente.
- Adicionaria concorrência interna complexa, mecanismos de descarte (*drop policy*) e sincronização frágil.

## Decisão
1. **Sem Fila em Memória:** O ingestor **não** mantém buffer de mensagens em memória durante indisponibilidades do PostgreSQL.
2. **Pausa de Consumo e Retenção no Broker:** Ao encontrar um erro temporário de banco (`TEMPORARY_DATABASE`):
   - O ingestor **não** envia o ACK MQTT para a mensagem em processamento.
   - O ingestor desconecta-se imediatamente do broker MQTT e pausa o consumo, impedindo que novas mensagens continuem sendo retiradas do broker e descartadas.
   - O broker MQTT (que mantém sessão persistente QoS 1 com `clean_session=false`) retém a mensagem na fila do servidor.
3. **Supervisor Ativo com Sondas e Backoff:**
   - O supervisor entra em loop de verificação, executando sondas periódicas no banco via query leve (`SELECT 1`).
   - As tentativas seguem **backoff exponencial truncado com jitter** (de 1s até o limite máximo de 30s) para não sobrecarregar o banco durante a recuperação.
4. **Reconexão e Reentrega:**
   - Quando a sonda confirma o restabelecimento do PostgreSQL, o ingestor reconecta ao MQTT e reassina o tópico.
   - O broker reentrega a mensagem pendente.
   - O ingestor insere a leitura de forma idempotente via `ON CONFLICT (event_id) DO NOTHING` e emite o ACK.

## Consequências
- Zero risco de perda de mensagens por falha de processo ou OOM durante quedas do banco de dados.
- Aproveitamento das garantias nativas de durabilidade e retenção do broker MQTT (HiveMQ / Mosquitto com volume persistente).
- Tratamento ordenado de restabelecimento de serviço sem picos de requisições concorrentes.
