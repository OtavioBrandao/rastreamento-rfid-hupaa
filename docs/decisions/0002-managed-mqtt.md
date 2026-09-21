# ADR 0002 — HiveMQ principal e Mosquitto para desenvolvimento

Data da decisão e consulta: **2026-09-05**. Implementação da ISS-001;
**aceite externo pendente**, issue permanece aberta. Atualiza a ADR 0001 para
o MVP; preserva seu ambiente de desenvolvimento e os registros históricos.

## Diagnóstico anterior

Base `main`, commit `8a2f424`, árvore limpa. Pipeline único: leitor/simulador →
Mosquitto → Paho 2.x → JSONL. `compose.yaml` e `mosquitto/mosquitto.dev.conf`
implementavam o broker anônimo em 1883; `mqtt_client.py` o ingestor;
`simulator.py` o publicador. Oito testes unitários passaram antes da alteração.
Havia ainda um smoke test Docker. QoS 1 e retain falso estavam no simulador;
o receptor preservava bytes, JSON, campos extras e erros de parsing.
Não havia TLS, convenção de tópicos por instalação/portal, nem conexão centralizada.

## Comparação oficial

| Item | HiveMQ Cloud Serverless | EMQX Cloud Serverless |
|---|---|---|
| Conexões simultâneas | 100 | 1.000 |
| Tráfego gratuito mensal | 10 GB | 1 GB |
| Minutos de sessão gratuitos | Franquia em minutos não publicada nas páginas atuais consultadas | 1 milhão/mês; inclui sessões persistentes offline |
| MQTT | 3.1, 3.1.1, 5 | 3.1, 3.1.1, 5 |
| Transporte externo | TLS; este projeto exige 8883 | TLS obrigatório; sem MQTT TCP em claro |
| Autenticação | Usuário/senha; não anônimo | Usuário/senha; não anônimo |
| ACL | Permissão customizada por tópico, uma por credencial | Controle por cliente e tópico |
| Mensagens/TPS | Taxa por cliente, TPS e cota mensal de mensagens atuais não especificados nas páginas consultadas; não assumir ilimitado | 1.000 TPS totais; 10 publicações/s por cliente; 1.000 entregas/s por cliente |
| Outros limites por cliente | Confirmar com suporte/painel antes de carga alta | 10 assinaturas; mensagem até 1 MB; sessão MQTT 3.x expira em 2 h |
| SLA | Sem SLA de disponibilidade | Tabela comercial informa 99,9%; sujeito às condições do serviço |
| Franquia excedida | Publicações excedentes rejeitadas por quota; cluster não para | Com spend limit 0, implantação para; reinício manual após renovação. Limite pago permite cobrança |

Fontes oficiais consultadas:

- [HiveMQ: planos](https://www.hivemq.com/products/mqtt-cloud-broker/).
- [HiveMQ: criação e limites](https://docs.hivemq.com/hivemq-cloud/quick-start-guide.html).
- [HiveMQ: autenticação e permissões](https://docs.hivemq.com/hivemq-cloud/authn-authz.html).
- [HiveMQ: franquia excedida, base oficial de suporte](https://hivemq.atlassian.net/wiki/spaces/HCSP/pages/2864840715/What+happens+when+I+exceed+traffic).
- [EMQX: planos e SLA](https://docs.emqx.com/en/cloud/latest/price/plans.html).
- [EMQX: quotas](https://docs.emqx.com/en/cloud/latest/create/restriction.html).
- [EMQX: cobrança e tráfego de entrada/saída](https://docs.emqx.com/en/cloud/latest/price/pricing.html).
- [EMQX: limite de gastos](https://docs.emqx.com/en/cloud/latest/deployments/spend_limit.html).
- [EMQX: reinício após franquia](https://docs.emqx.com/en/cloud/latest/faq/deploy.html).
- [EMQX: introdução](https://docs.emqx.com/en/cloud/latest/quick_start/introduction.html).

Não foram reaproveitados como limites atuais números de discussões antigas sobre
throughput ou tamanho de mensagem do HiveMQ. Confirmar limites não publicados
com o provedor se o perfil medido exigir. O comportamento de quota do HiveMQ vem
de artigo oficial de 2024 ainda disponível na consulta; confirmar no painel ao criar o cluster.

## Decisão e orçamento de volume

HiveMQ é a escolha confirmada pela equipe: três conexões operacionais cabem
confortavelmente em 100, e 10 GB dão mais margem ao experimento que 1 GB.
TLS e permissões customizadas atendem ao isolamento necessário. Não há garantia
de disponibilidade hospitalar; a escolha é experimental, não um compromisso de SLA.

Conexões: 2 leitores + 1 ingestor contínuo = **3**; reservar hipoteticamente
2 clientes auxiliares = **5 simultâneos**. Em 30 dias, três sessões contínuas
consomem `3 × 30 × 24 × 60 = 129.600` minutos. Dois auxiliares por 1 h/dia
somam 3.600 minutos: **133.200/mês**, também abaixo da cota EMQX.

Hipóteses de tráfego, não requisitos nem medições: payload de 250 bytes,
reserva de 100 bytes de tópico/protocolo por publicação/entrega, um assinante,
margem de 50% para ACKs, TLS, keepalive, reconexões e variação de tamanho.
A reserva não reproduz exatamente a medição do provedor: calibrar com o painel.
EMQX contabiliza entrada e saída; para HiveMQ usamos conservadoramente ambas
até confirmar a granularidade contabilizada no cluster.

`N = leitores × mensagens/s/leitor × horas/dia × 3.600 × dias`

`B = N × (payload + reserva) × (1 entrada + assinantes) × 1,5`

| Hipótese com 2 leitores, 30 dias | Publicações/mês | Tráfego projetado (GB decimais) |
|---|---:|---:|
| 1 msg/s/leitor, 8 h/dia | 1.728.000 | 1,8144 |
| 1 msg/s/leitor, 24 h/dia | 5.184.000 | 5,4432 |
| 10 msg/s/leitor, 8 h/dia | 17.280.000 | 18,144 |

No primeiro cenário: 432 MB de payload de entrada; 604,8 MB com a reserva;
1.209,6 MB incluindo uma entrega; 1.814,4 MB com margem. A taxa máxima
aproximada dentro de 10 GB seria 5,51 msg/s/leitor a 8 h/dia, com essas hipóteses.
Cada assinante adicional aumenta o tráfego de entrega. Repetir testes no Mosquitto
economiza franquia. Ainda é necessário medir taxa, bytes reais, duty cycle, perdas,
retransmissões e número futuro de leitores; não há previsão de expansão confirmada.

## Arquitetura e limites

Anterior: `EZ700/simulador → Mosquitto local → ingestor → JSONL`.

Principal: `leitor/simulador → HiveMQ com TLS → mesmo ingestor → JSONL local`.

Desenvolvimento/offline: `leitor/simulador → Mosquitto → mesmo ingestor → JSONL`.
Seleção manual por `MQTT_MODE=local|cloud`; sem fallback automático e sem ponte.
O notebook nunca cria hotspot. Banco, CRUD, inferência e dashboard ficam fora.

Ver [guia operacional](../implementations/iss-001-mqtt-ingestion.md), [roteiro de campo](../experiments/mqtt/iss001-managed-validation.md)
e [evidências reais](../experiments/mqtt/iss001-evidence-local.md).
