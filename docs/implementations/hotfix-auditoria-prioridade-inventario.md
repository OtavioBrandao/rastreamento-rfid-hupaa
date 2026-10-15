# Correção — detalhe da auditoria e prioridade do inventário

## Problema e importância para o MVP

Ao clicar em “Ver registro”, o detalhe da auditoria aparecia depois da tabela
inteira, sem deslocar a tela nem receber foco. Com dezenas de registros, parecia
que o botão não funcionava. O inventário também usava ordem alfabética, misturando
equipamentos recém-lidos e em trânsito com cadastros antigos em atenção.

Estes ajustes permitem conferir alterações e encontrar os equipamentos relevantes
durante o ensaio do MVP.

## O que foi feito

- O detalhe da auditoria abre em um `dialog` modal nativo, visível sobre a tabela,
  com foco no botão de fechar. Escape, botão e clique fora do conteúdo fecham o
  detalhe e devolvem o foco ao botão que o abriu. Filtros, paginação, atualização
  automática, eventos relacionados e a consulta somente de leitura permanecem.
- O dashboard solicita `sort=prioridade` em `/api/ativos`. A API ordena **antes de
  paginar**: tags lidas nos últimos 30 segundos; equipamentos em trânsito
  (`disponivel`); atenção necessária; sem zona confirmada; fora de serviço.
- Nas leituras atuais, a mais recente vem primeiro; em seguida, a última detecção
  confirmada mais recente, nome e ID desempatam. Só a associação ativa do EPC
  pode promover um equipamento. Uma leitura antiga perde a prioridade sem exigir
  nova leitura; a próxima consulta aplica o mesmo relógio a toda a página.
- A leitura recente mantém os rótulos de status e a zona existentes. Não confirma
  localização nem muda critérios de inferência. As ordenações anteriores da API
  e o padrão por nome continuam disponíveis aos outros consumidores.

O intervalo de presença de 30 segundos acompanha `PRESENCE_FRESH_MS`, já usado
pela badge “Lida agora”. Não é o limite de recência da zona confirmada.

## Validação

- Frontend: testes do modal com 50 registros, filtros, fechamento, retorno de
  foco, atualização e preservação da ordenação em filtros/paginação.
- PostgreSQL 16 descartável: prioridade global entre páginas, expiração da
  presença, exclusão de EPC desvinculado, contrato HTTP e preservação da zona.
- Navegador com API sintética: abertura imediata, antes/depois, Escape e retorno
  do foco, eventos relacionados, paginação e limpeza dos filtros.
- Build TypeScript/Vite, Ruff e `git diff --check`.

Resultado local: **60 testes de frontend e 82 testes Python aprovados**, incluindo
a regressão de passagem, direção e localização em PostgreSQL 16 descartável.

Nenhuma alteração no ingestor, debounce, detector de passagem, direção ou
projeção de localização. A análise separada do equipamento 3 está em
[investigação de 15/10/2026](investigacao-equipamento-3-2026-10-15.md).
