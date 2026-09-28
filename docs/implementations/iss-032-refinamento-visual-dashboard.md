# ISS-032 — Refinamento visual do dashboard

## Issue e importância para o MVP

A interface inicial da ISS-032 ainda trazia textos redundantes, uma marca provisória e indicadores com faixas coloridas no topo. Esses detalhes prejudicavam a leitura rápida da situação dos equipamentos e a clareza visual da demonstração do MVP no HUPAA/UFAL. A tarefa é estritamente de apresentação: a localização continua aproximada pela última zona conhecida e os dados e contratos existentes não foram alterados.

## O que foi feito

- Removidos o indicador “MVP experimental · API local” da sidebar, o contexto “Rastreamento aproximado por zona” do header, o rodapé textual e o subtítulo repetido “Consulta de ativos do HUPAA”. O identificador “PAINEL OPERACIONAL / HUPAA” permanece acima do título da página.
- Substituída a marca provisória por um SVG escalável com dois arcos brancos de cada lado e cruz vermelha. A marca mantém o nome e a assinatura HUPAA · UFAL no alinhamento da sidebar.
- Os cinco cards de situação agora usam contorno completo e selo circular com ícone. Os rótulos, números, dados e comportamento foram preservados. O fundo permanece branco.
- As cores dos cards foram centralizadas em tokens `--kpi-*` no CSS, para limitar a mudança visual aos indicadores. Verde, âmbar, vermelho e grafite mais presentes distinguem os estados; o total mantém o azul-marinho do aplicativo.

## Validação

O branco dos ícones sobre os selos alcança pelo menos 5,02:1 de contraste, e o texto dos rótulos sobre branco alcança 7,84:1. Os ícones e rótulos comunicam cada estado sem depender apenas da cor. O frontend foi verificado com build TypeScript/Vite e testes Vitest; o projeto não define comando de lint próprio para o frontend.
