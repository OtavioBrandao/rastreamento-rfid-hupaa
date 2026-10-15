# Revisão da Sprint 2 após ensaio sintético gerenciado — 26/09/2026

## Escopo e evidência recebida

O operador executou a opção 4 do launcher no Windows, com publicação no HiveMQ Cloud e persistência no Neon. Foram fornecidos o resumo do launcher, a captura das mensagens MQTT, os logs do ingestor e do observador do banco, além de uma captura da tabela `leituras_brutas`. Este registro resume a evidência sem reproduzir credenciais ou dados de conexão.

O launcher confirmou **100 leituras publicadas e verificadas** para um EPC de teste, seguidas da **passagem 3, A→B**, **movimentação 3** e **última zona 2**. A captura MQTT contém 100 objetos JSON com as chaves `epc`, `rssi`, `antenna` e `timestamp`: 70 leituras na antena 1 e 30 na antena 2. O observador do banco e a captura do Neon mostram leituras persistidas nas duas antenas; o observador também registrou a passagem, a movimentação e a zona final. Os logs do ingestor mostram outras passagens durante a sessão, mas a verificação deste ensaio se baseia na passagem 3 associada ao intervalo de leituras publicado pelo launcher.

O formato JSON reproduz a amostra observada anteriormente no terminal do leitor. Isso **não valida** a semântica do contador `timestamp`, as variações de payload do firmware, o comportamento de RF ou a conexão física do EZ700 ao HiveMQ Cloud.

## Situação das issues da Sprint 2

| Issue | Evidência deste ensaio | Evidência complementar | Pendente |
|---|---|---|---|
| [ISS-014 — debounce](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/issues/16) | As leituras brutas atravessaram o pipeline sem perda observada no verificador. | Testes unitários cobrem consolidação, reordenação e janela temporal. | Este ensaio em nuvem não demonstrou consolidação de várias leituras em uma única observação: os logs mostram `reading_count=1` nas observações e `readings_incorporated=0`. Testar rajadas dentro da janela de 250 ms e calibrar com RF real. |
| [ISS-015 — passagem](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/issues/17) | A sequência antena 1→2 produziu uma passagem rastreável. | Testes cobrem correlação e casos sem passagem. | Calibrar a janela de passagem e os falsos positivos com leitor físico. |
| [ISS-016 — direção](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/issues/18) | A passagem do ensaio foi confirmada A→B, zona 1→2. | Testes cobrem B→A, ambiguidade e ordenação. | Validar direção, tolerância temporal e sincronismo com travessias físicas rotuladas nos dois sentidos. |
| [ISS-017 — última localização](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/issues/19) | O equipamento terminou na zona 2 após a passagem confirmada. | Testes cobrem atualização e proteção contra regressão por eventos atrasados. | Validar a interpretação operacional da última zona no campo. |
| [ISS-018 — movimentações](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/issues/20) | O banco e os logs registraram a movimentação associada à passagem. | Testes cobrem histórico e correção manual. | Exercitar o fluxo operacional completo com equipamento e leitor reais. |

As cinco issues estão fechadas no GitHub, mas isso não equivale ao aceite físico. Os critérios de revisão pela dupla ainda aparecem desmarcados nas respectivas issues. Nenhuma calibração de limiares deve ser considerada concluída com base neste ensaio.

## Validação automatizada nesta revisão

- Testes unitários de debounce, passagem, direção, movimentação e localização: **68 passaram**.
- Testes de integração correspondentes: **4 passaram, 35 ignorados**, pois `TEST_DATABASE_URL` não estava disponível neste ambiente. A execução gerenciada do operador fornece evidência de ponta a ponta para o percurso A→B, mas não substitui todos os cenários integrados ignorados.

## Decisão sobre a Sprint 3

**A implementação de software pode avançar agora**, com estas dependências explícitas:

| Trabalho | Decisão |
|---|---|
| [ISS-019 — busca](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/issues/21), [ISS-020 — listagem por zona](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/issues/22), [ISS-021 — última zona/data na interface](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/issues/23) | Avançar. Exibir **última passagem confirmada**, horário e recência; não afirmar localização contínua ou presença física atual. |
| [ISS-022 — recência](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/issues/24) | A lógica de backend e uma apresentação demonstrativa já existem. Integrar com dados reais na interface; manter o limiar inicial de 30 minutos como provisório até calibração física. |
| [ISS-023 — planta 2D](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/issues/25) | Avançar com planta simplificada de laboratório prevista na issue. A planta real do HUPAA depende de autorização e mapeamento; não inventar coordenadas. |
| [ISS-032B — integração do painel com APIs](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/issues/62) | Avançar depois de estabilizar os contratos das consultas acima. O painel atual usa dados demonstrativos. |
| [Alinhamento com TI do HUPAA](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/issues/33) e [seguimento do hardware](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/issues/42) | Permanecem dependências externas para ensaio físico e implantação. O transporte MQTTS direto do EZ700 ao HiveMQ Cloud, com o firmware testado, ainda requer solução ou alternativa validada. |

Assim, a Sprint 3 **não precisa esperar** o teste físico para construir e testar suas consultas e interface com dados sintéticos. O aceite da operação física e da rede hospitalar permanece pendente. O ensaio atual não justifica prometer que o leitor publicará diretamente em nuvem ou que os limiares escolhidos funcionarão sem ajuste no campo.
