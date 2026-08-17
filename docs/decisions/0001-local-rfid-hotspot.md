# ADR 0001 — Hotspot local para o primeiro experimento de conectividade

- **Status:** proposto para validação
- **Data:** 2026-08-17

## Contexto

O MVP precisará receber eventos de leitores RFID em uma rede local, mas a configuração real do Identix EZ700 e os protocolos e payloads disponíveis ainda não foram validados. Antes de escolher backend ou integração, é necessário confirmar uma premissa menor: um notebook Ubuntu consegue oferecer uma rede Wi-Fi isolada e um serviço local acessível por outro dispositivo, sem internet ou dependência da rede hospitalar.

## Decisão

Validar primeiro um hotspot criado pelo NetworkManager no notebook Ubuntu. O notebook usará endereço local estático no perfil compartilhado e hospedará uma página HTTP mínima. A decisão cobre somente o experimento; não define a arquitetura de produção do hospital.

## Alternativas consideradas

- **Hotspot no notebook:** usa o equipamento já disponível, reduz dependências externas e permite testar rapidamente conectividade local e operação offline.
- **Roteador ou ponto de acesso Wi-Fi offline:** tende a ser mais estável e flexível, mas exige equipamento e configuração adicionais antes de validar a hipótese mais simples.
- **Rede institucional/hospitalar:** pode oferecer infraestrutura gerenciada, porém depende de autorização, políticas, segmentação, firewall e disponibilidade de terceiros.
- **Switch Ethernet:** oferece conexão cabeada previsível, mas não valida clientes Wi-Fi e pode exigir adaptadores e cabeamento. Continua sendo uma alternativa futura, não um requisito deste experimento.

## Por que começar pelo hotspot do notebook

É a alternativa com menor custo de preparação e permite isolar a validação do acesso cliente–servidor das decisões ainda abertas sobre leitor, backend e rede institucional. Um resultado positivo reduz uma incerteza imediata; um resultado negativo produz evidência para escolher um ponto de acesso dedicado ou outra topologia.

## Riscos e limitações

- A interface Wi-Fi pode não suportar modo AP.
- Uma única placa pode não manter simultaneamente o hotspot e outra conexão Wi-Fi.
- Driver, firmware, NetworkManager, firewall e economia de energia podem afetar estabilidade.
- O compartilhamento IPv4 do NetworkManager pode depender de componentes adicionais da instalação.
- Alcance, concorrência, segurança operacional e disponibilidade de um notebook não representam requisitos de produção.
- Um telefone conectado não valida a conectividade nem o formato de mensagens do EZ700.

## Condições para reconsiderar

A decisão deve ser revista se o adaptador não suportar AP, se a atribuição de IP ou a estabilidade forem insuficientes, se o leitor exigir Ethernet, se políticas institucionais impedirem o hotspot, se houver requisito de maior cobertura ou disponibilidade, ou se a validação física indicar que um roteador/AP dedicado, a rede institucional ou uma topologia cabeada é mais adequada.
