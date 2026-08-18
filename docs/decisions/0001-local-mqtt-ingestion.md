# ADR 0001 — Ingestão MQTT local no notebook

- **Status:** aceita para a primeira camada do MVP
- **Data:** 2026-08-17

## Contexto

Vários leitores RFID precisam enviar eventos continuamente ao mesmo notebook, sem que esta etapa dependa de internet, nuvem ou banco de dados externo. A tentativa de usar o próprio notebook como hotspot mostrou instabilidade e acoplava a recepção dos dados à criação da rede.

Segundo a documentação disponível, o Identix EZ700 oferece Wi-Fi 2,4 GHz e MQTT(S), mas firmware, tópicos, credenciais e payload reais ainda precisam de validação física.

## Decisão

O notebook atuará somente como broker Mosquitto, receptor Python e armazenamento local JSONL. Leitores e notebook usarão a mesma rede Wi-Fi, inicialmente um hotspot de celular ou a rede institucional.

O receptor assinará `rfid/+/tags` por padrão. O tópico é configurável e poderá ser temporariamente alterado para `#` durante a descoberta controlada do leitor. O payload documentado pela Identix será preservado sem validação rígida de campos nesta fase.

## Motivos

- MQTT foi projetado para publicação e assinatura contínuas e permite múltiplos leitores.
- A separação entre rede Wi-Fi e transporte MQTT permite testar diferentes redes sem alterar a aplicação.
- JSONL oferece persistência append-only simples, auditável e sem serviço externo.
- Mosquitto e Paho permitem um caminho mínimo para validar o hardware antes de decisões de produção.

## Consequências e limites

- A configuração de desenvolvimento aceita MQTT anônimo e sem TLS somente em rede controlada.
- O broker não deve ser exposto à internet.
- Hotspot de celular ou Wi-Fi institucional pode isolar clientes ou bloquear a porta 1883.
- O IP do notebook precisa ser conhecido pelos leitores e pode variar entre conexões.
- O JSONL não substitui o banco de dados futuro nem resolve deduplicação, regras de portal ou dashboard.
- A arquitetura será revista após os testes com EZ700 físico, múltiplos leitores e quedas de rede.

## Alternativas consideradas

- HTTP, sockets e WebSockets continuam possíveis, mas não serão implementados antes da validação MQTT.
- Broker em nuvem exigiria internet e ampliaria prematuramente o escopo e a superfície de segurança.
- Notebook como hotspot foi retirado por instabilidade e dependência operacional.
- Roteador local próprio permanece como alternativa de rede caso os dois testes iniciais falhem.
