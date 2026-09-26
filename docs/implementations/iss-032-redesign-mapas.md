# ISS-032 — Redesenho do dashboard e protótipo de mapas

## Issue e importância para o MVP

A Issue #59 (ISS-032) busca permitir que a engenharia clínica encontre equipamentos sem conhecer a infraestrutura RFID. O PR #61 incorporou a Etapa A: React + TypeScript + Vite, busca local, estados de carregamento/vazio/erro, quatro indicadores de recência e uma rota de mapa reservada. Esta entrega usa essa implementação como base e amplia a visualização operacional. A localização continua **aproximada pela última zona detectada**; nenhum ponto da planta afirma posição exata.

O mapa também prepara uma ferramenta de calibração para a equipe EASY. Distinguir visualmente a antena que captou uma tag ajuda a conferir se a sala inferida corresponde ao teste físico. A posição dos equipamentos e do hardware ainda depende de calibração no HUPAA e no laboratório.

## O que foi feito

- Navegação lateral escura, tipografia e cores semânticas documentadas em `frontend/design-system.md`, com rótulo e ícone além de cada cor de status.
- Cinco indicadores operacionais, tabela com última zona e recência, disponibilidade por departamento, atenção prioritária, tendência sintética de 30 dias, atividade recente e painel lateral compartilhado de equipamento.
- `FloorMap` reutilizado pelas abas HUPAA e EASY. O esquema do 2º pavimento apresenta seis tipos de zona, camadas, filtros e marcadores clicáveis. A planta é ilustrativa, inspirada na figura de setorização fornecida.
- O esquema de duas salas do laboratório apresenta leitor azul central e duas antenas vermelhas. Botões de simulação geram EPC, antena, sala inferida e horário no log, com pulso de 1,7 s na antena correspondente.
- `frontend/src/config/mapaConfig.ts` concentra os polígonos e as coordenadas percentuais para recalibração sem alteração dos componentes.
- Foram preservados a navegação por fragmento, a busca demonstrativa e os estados carregando, vazio e erro da Etapa A. Há verificações de navegação, filtros, painel de detalhe e log simulado.

## Limites e integração futura

Todos os ativos, status operacionais, datas, série histórica, leituras e posições mostrados são **fictícios**. A API atual não oferece um contrato consolidado para o painel nem um stream de leituras para o navegador. Por isso, o laboratório identifica a origem como “simulação local”; não há WebSocket, atualização real ou conexão presumida com o Identix EZ700. A camada `frontend/src/services/dashboard.ts` segue como fronteira para integração futura. Os `TODO(API)` indicam os dados a negociar com o backend: agregados, equipamento por zona, histórico e eventos do laboratório. O mapa hospitalar mostra apenas os exemplos do 2º pavimento com zona conhecida; equipamentos sem detecção ou de outros andares continuam consultáveis no Dashboard.

O desenho usa componentes React locais e SVG de interface, sem instalar nova biblioteca de componentes. Isso mantém a Etapa A pequena e executável offline. Os controles têm semântica e foco visível; a experiência física em tablet ainda precisa de observação com usuários.

## Execução e validação

```bash
cd frontend
npm ci
npm test
npm run build
npm run dev
```

Abra `http://localhost:5173/`. As rotas são `#/` e `#/mapa`; `?estado=vazio` e `?estado=erro` preservam os cenários demonstrativos do dashboard. A integração real com a API e a validação física permanecem pendentes da definição de contratos e da disponibilidade do hardware.
