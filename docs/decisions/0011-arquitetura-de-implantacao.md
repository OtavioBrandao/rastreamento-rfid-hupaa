# ADR 0011 — Arquitetura de implantação: monólito em contêineres, mesma origem

- Status: Proposta (provedor ainda não escolhido)
- Data: 2026-10-23

## Contexto

Após o Marco 2 o sistema precisa de um caminho de hospedagem que não dependa
do notebook de desenvolvimento. O ingestor MQTT é um processo contínuo; o
EZ700 não publicou direto no HiveMQ por MQTTS nos ensaios, mas funcionou via
bridge Mosquitto local.

## Decisão

- Manter o monólito modular: **uma imagem de backend** com três comandos
  (API, ingestor, migrations) e **uma imagem web** (Nginx + build React) que
  faz proxy da API na mesma origem.
- Referência: Docker Compose num host (VPS) atrás de proxy TLS; os mesmos
  contêineres servem a um PaaS com *web service* + *background worker*.
- PostgreSQL gerenciado e HiveMQ Cloud externos; bridge Mosquitto opcional na
  rede do hospital; conexão direta mantida como possibilidade a validar.
- Sem microsserviços nem Kubernetes até haver necessidade demonstrada.

## Consequências

- Cookie `SameSite=Strict` e ausência de CORS preservados.
- Falha da API não afeta o ACK do ingestor e vice-versa.
- A equipe (ou o provedor) responde por TLS, backups e atualizações do host.
- Detalhes e alternativas em `docs/operations/deploy.md`.
