# ADR 0010 — Simulador web publicando no pipeline real

- Status: Aceita
- Data: 2026-10-23

## Contexto

O simulador Flet era desktop, só EASY, e as demonstrações ao HUPAA precisam
de uma planta configurável no navegador, com duas abas (configuração e
controle) e sem lógica paralela que altere a zona no frontend.

## Decisão

1. Um único simulador web; EASY e HUPAA são presets de layout.
2. Iniciar uma sessão **cadastra a topologia** (zonas, portais, leitores
   `sim-*`, antenas, mapeamentos versionados) e um motor no processo da API
   publica leituras no MQTT no contrato do EZ700. Ingestor, inferência e
   projeção não mudam.
3. O estado compartilhado (layouts, sessões, itens) fica no PostgreSQL com
   versão e trava de linha; as abas sincronizam por polling curto.
4. Isolamento por `APP_ENV` (bloqueado em produção), `reader_id`/serial
   próprios por layout e credencial MQTT de publicação própria, só no servidor.

## Consequências

- A demonstração exercita o pipeline aprovado no Marco 2; só a leitura física
  é substituída.
- O motor exige um único publicador: advisory lock no PostgreSQL.
- A API passa a ter um componente opcional com MQTT (desligado por padrão).
- Polling em vez de WebSocket: simples, compatível com qualquer proxy;
  reavaliar se o número de abas/sessões crescer.
