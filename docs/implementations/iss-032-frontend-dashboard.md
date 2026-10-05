# ISS-032 — Frontend e dashboard operacional (Etapa A)

## Objetivo e importância para o MVP

A Issue #59 (ISS-032, E5) pede uma interface que ajude trabalhadores do hospital a encontrar equipamentos com rapidez. O pipeline atual já registra movimentações e última zona, mas uma pessoa em atividade assistencial precisa visualizar nome, última zona detectada, tempo da detecção e confiabilidade da informação sem conhecer a infraestrutura RFID.

> A descrição da Etapa A abaixo registra o estado histórico da entrega visual. A integração real da Issue #62 (ISS-032B) está documentada ao final deste arquivo.

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

## ISS-032B — integração do painel com as APIs reais (Issue #62)

### Importância e estado anterior

A base visual da #59 já existia. As entregas #66 e #67 já tinham ligado busca, paginação, última zona hierárquica e histórico por equipamento ao backend. A ISS-022 já classificava a recência no servidor. Faltavam um feed de atividade global, indicadores em uma consulta agregada e limpeza explícita dos dados de todas as seções após falha ou troca de busca.

### Fluxo e contratos

O React chama `frontend/src/services/dashboard.ts`, que usa `fetch` para a FastAPI. A API consulta os serviços e o PostgreSQL. O painel consome:

- `GET /api/ativos`: busca paginada por nome/patrimônio, EPC, tipo, status e zona. A resposta já traz última zona como andar → setor → zona, timestamp e status derivado da ISS-022. O navegador não recalcula o limite temporal.
- `GET /api/dashboard/resumo`: `{registered, disponivel, atencao, fora_de_servico, nunca_detectado}`. Uma consulta SQL agregada classifica os contadores com o mesmo relógio e limite usados na busca, sem transferir o inventário inteiro.
- `GET /api/dashboard/atividade?limit=8`: `{items: [...]}` com no máximo 20 registros permitidos. Cada item contém ID, equipamento, zonas de origem/destino, horário da movimentação e origem do registro. Ordenação determinística por `movimentada_em DESC, id DESC`; índice parcial global dá suporte ao limite. O feed mostra movimentações confirmadas e correções manuais do ledger, não leituras brutas isoladas.
- `GET /equipamentos/{id}/movimentacoes`: histórico paginado no detalhe, já existente da ISS-018/#67.
- `GET /tipos-equipamento?size=100` e `GET /localizacoes/arvore`: opções de filtro já existentes.

O proxy do Vite encaminha `/api`, `/equipamentos`, `/tipos-equipamento`, `/localizacoes` e `/auth` (sessão, desde a [ISS-027](iss-027-perfis-rbac.md)) para `http://127.0.0.1:8000`; `/usuarios` fica de fora porque não há tela de usuários. O fluxo já usado com banco externo continua em **um comando para subir a API**, a partir da raiz do checkout: `python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --env-file .env.cloud`. Em outra janela, iniciar `npm run dev` em `frontend/` do mesmo checkout. Não é necessário subir um PostgreSQL Docker adicional nesse fluxo.

Quando o código do PR está em um worktree separado, pode-se manter `.venv` e `.env.cloud` na pasta original: executar ali o mesmo comando, acrescentando `--app-dir <caminho-do-worktree>` para carregar `api.main` do PR. O frontend deve rodar a partir de `frontend/` do worktree. A migration do índice é aplicada no banco do ambiente no processo normal de implantação; iniciar a API não executa migrations automaticamente. Em hospedagem separada, `VITE_API_BASE_URL` aponta para a API e a origem precisa ser autorizada na configuração de implantação; o projeto não abre CORS irrestrito.

### Estados e limites

Inventário, indicadores, atividade e opções de filtro carregam de forma independente. Falha na busca limpa a página anterior e mostra erro com nova tentativa. Indicadores e atividade também são invalidados em falha e exibem erro específico; uma resposta tardia de requisição abortada não restaura dados antigos. Lista vazia e ausência de movimentações têm mensagens próprias. O botão de nova tentativa repete as leituras.

A localização continua aproximada pela última zona confirmada, sem coordenada física nem posição atual garantida. Equipamento nunca detectado permanece sem zona e sem horário. “Disponível” e “Atenção” são rótulos derivados de cadastro e recência provisória, não disponibilidade clínica; `offline` não é inferido do silêncio RFID. A planta física da ISS-023, WebSocket, autenticação e validação física do EZ700 permanecem fora desta entrega.
