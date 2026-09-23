# ISS-032 — Frontend e dashboard operacional (Etapa A)

## Objetivo e importância para o MVP

A Issue #59 (ISS-032, E5) pede uma interface que ajude trabalhadores do hospital a encontrar equipamentos com rapidez. O pipeline atual já registra movimentações e última zona, mas uma pessoa em atividade assistencial precisa visualizar nome, última zona detectada, tempo da detecção e confiabilidade da informação sem conhecer a infraestrutura RFID.

**Esta implementação corresponde à Etapa A da ISS-032 e não conclui a issue.** A tela é uma fundação visual para revisão com usuários. Os dados exibidos são fictícios e não representam a situação do HUPAA.

## Stack e organização

O frontend fica em `frontend/` e usa React, TypeScript e Vite. São ferramentas maduras para uma interface pequena; não há gerenciamento de estado global nem dependências de gráficos. Vitest, React Testing Library e jsdom cobrem os estados e a navegação. A navegação usa fragmentos (`#/` e `#/mapa`), funcionando em hospedagem estática local sem regras adicionais de reescrita.

- `src/components/`: shell, navegação, busca, resumo, itens e status.
- `src/pages/`: Dashboard e placeholder de Mapa/Planta.
- `src/types/`: tipos locais mínimos para a tela.
- `src/mocks/`: fixtures fictícias, identificadas como dados de desenvolvimento.
- `src/services/`: único ponto de acesso aos dados e filtro demonstrativo.
- `src/styles/`: estilos responsivos e estados de foco.
- `src/test/`: testes de comportamento.

Os tipos e a função `getDashboard` **não são contratos de API definitivos**. A API existente oferece cadastros e consultas do domínio; esta etapa não inventa endpoints de agregação, busca ou status. A camada de serviço é o ponto previsto para substituir os mocks pelas APIs reais. O filtro local faz apenas correspondência simples em nome, tipo, patrimônio e EPC das fixtures.

## Decisões de UX

A tela prioriza a busca e mostra os quatro números de resumo com leitura rápida. A lista expõe somente dados operacionais. Cada status combina texto com sinal visual, sem depender apenas da cor. O estado desatualizado avisa que o equipamento pode estar em outro local. A tela usa áreas clicáveis grandes, foco visível, semântica HTML e layout para desktop, tablet e telas menores.

**A localização é aproximada por zona**, baseada na última detecção conhecida. Ela não indica posição exata nem garante que o equipamento ainda esteja na zona. Um equipamento nunca detectado recebe “Nenhuma localização registrada”; a tela não inventa uma zona. Os estados carregando, vazio e erro têm mensagens distintas; após erro, os dados são limpos.

## Execução local

Com Node.js e npm instalados:

```bash
cd frontend
npm ci
npm run dev
```

Abra `http://localhost:5173/`. Para testar os estados da interface, use `http://localhost:5173/?estado=vazio` ou `http://localhost:5173/?estado=erro`. Esses parâmetros só simulam respostas da camada de serviço; não são parte de uma API. A mensagem “Ambiente demonstrativo” identifica a natureza dos dados.

```bash
cd frontend
npm test
npm run build
```

Na raiz do repositório, as verificações Python continuam sendo `python -m pytest -q` e `python -m ruff check --select E4,E7,E9,F,I .`.

## O que foi feito e o que permanece pendente

Esta Etapa A entrega shell, navegação Dashboard ↔ Mapa/Planta, busca demonstrativa, cards, lista de detecções, três estados de status e estados de carregamento, vazio e erro. O mapa é apenas um placeholder. A #59 permanece aberta para revisão visual e integração posterior.

Dependências explícitas para substituir os dados fictícios:

- **#19 / ISS-017:** a projeção da última zona já existe no domínio; falta sua apresentação integrada na tela.
- **#20 / ISS-018:** o histórico de movimentações já existe no domínio; a lista visual precisará de uma consulta operacional adequada.
- **#21 / ISS-019:** busca real por equipamento, patrimônio ou EPC.
- **#22 / ISS-020:** listagem de ativos por zona; será necessária para a navegação espacial quando o mapa for implementado.
- **#23 / ISS-021:** apresentação da última localização e do horário da detecção; substituirá os textos fictícios dos itens.
- **ISS-022:** regra e exposição do estado recente/desatualizado. Nesta etapa o status já vem pronto na fixture.
- **#25 / ISS-023 (mapa/planta):** planta 2D, zonas selecionáveis, portais e ativos por zona. A rota atual apenas reserva espaço visual.

Os indicadores agregados e a lista operacional também precisarão de endpoints de leitura apropriados à #59, sem cálculo a partir de toda a base no navegador. Os contratos exatos para os componentes serão confirmados na integração. Esta etapa não redefine seus escopos.
