# ISS-033 — Atualização automática e recuperação global

## Issue e importância para o MVP

A issue #71 nasceu da necessidade de atualizar os dados sem recarregar a
página. Em 05/10/2026, o responsável substituiu os três botões propostos por
atualização automática de todas as informações visíveis e **um único botão
global** de recuperação. O escopo inclui dashboard, mapas e painel de detalhe.

## Implementação

- Consultas a cada **2 segundos**: inventário filtrado/paginado, indicadores,
  atividade recente, opções de tipo/zona, ativos do mapa, cadastro de zonas e
  portais, detalhe do equipamento e página aberta de seu histórico.
- As leituras das antenas EASY continuam consultadas a cada **1 segundo**,
  com cursor e pulso visual distintos da última zona confirmada.
- `LiveProvider` coordena o botão “Atualizar tudo”. Ele renova todos os
  recursos montados, inclusive o mapa, metadados e histórico aberto, sem
  reload e sem resetar os filtros ou a página escolhida. Telas não montadas
  consultam dados frescos ao serem abertas.
- Cada recurso evita consultas sobrepostas. O botão indica atividade e fica
  desabilitado enquanto há requisições; cada chamada HTTP tem limite de 8
  segundos, aborta ao sair da tela e não usa cache do navegador.
- Uma falha transitória mantém o último resultado com aviso e tenta novamente.
  Trocar filtro, página ou equipamento oculta resultados da chave anterior;
  respostas antigas não substituem a consulta atual. A topologia do mapa
  recebe tratamento conservador: falhas ativam a alternativa textual.
- O rótulo de `disponivel` passa a **“Em trânsito”** nos indicadores, filtros
  e badges compartilhadas. É uma mudança de apresentação solicitada pelo
  responsável: o contrato e a regra de recência da API permanecem iguais.
  O rótulo não prova movimento contínuo ou posição exata do equipamento.

## Latência e limites

É atualização por consultas periódicas, próxima de tempo real, sem WebSocket.
A mudança fica visível no próximo ciclo **após estar disponível na API**,
somando latência de rede/consulta. Não reduz a janela de inferência RFID nem
garante dois segundos durante falhas, consultas lentas ou suspensão da aba.
Em uma falha persistente, o botão não substitui a correção do serviço.

## Validação — 05/10/2026

`npm --prefix frontend test`: **21 testes aprovados**. Os novos cenários
verificam atualização sem clique de inventário, indicadores, opções, atividade,
detalhes, histórico e mapa EASY; recuperação automática e global; preservação
de dados em falha; ausência de sobreposição; timeout/cancelamento; atualização
de contagens e leituras. A suíte anterior também verifica respostas atrasadas.

`npm --prefix frontend run build`: aprovado. Conferência visual com API
sintética em desktop e móvel (390 × 844), sem usar banco/credenciais reais.
A regressão Python resultou em 356 testes e 90 subtestes aprovados, com 532
testes dependentes de configuração/serviços locais pulados. Os testes de
integração PostgreSQL/MQTT ficam a cargo do CI e dos ensaios apropriados.

O CI agora inclui o job Frontend com Node.js 22, `npm ci`, testes e build,
além dos jobs existentes de lint Python, testes e migrations.
