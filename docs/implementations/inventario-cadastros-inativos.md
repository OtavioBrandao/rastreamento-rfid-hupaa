# Inventário operacional e cadastros inativos

Sessões repetidas de laboratório acumulam cadastros e tornam a demonstração
difícil de acompanhar. Apagar esses equipamentos perderia vínculos necessários
à interpretação dos testes anteriores.

O dashboard abre com **cadastros ativos**. A opção **Mostrar cadastros inativos
(ensaios arquivados)** inclui os anteriores sem reativá-los. Escolher o filtro
**Fora de serviço** também inclui os inativos automaticamente. O total, os
indicadores e as movimentações seguem a mesma seleção de ciclo de vida; os
outros filtros continuam cumulativos na tabela.

Mapas e contagens operacionais de leituras consideram equipamentos ativos.
Tags de equipamentos inativos são excluídas desse recorte, sem serem
reclassificadas como tags desconhecidas. Tags avulsas continuam visíveis.
Consulta direta do equipamento e seu histórico permanecem disponíveis.

A API aceita `somente_ativos=true` em `/api/ativos`, `/api/dashboard/resumo`,
`/api/dashboard/atividade` e `/api/leituras/resumo`. O padrão HTTP permanece
`false` para compatibilidade com consumidores existentes. A interface solicita
o recorte operacional explicitamente. Não existe exclusão física nesse fluxo.

A validação usa PostgreSQL descartável para comparar visão completa e ativa,
contagens, EPC inativo sem leitura e tag desconhecida, verificando ao final
que cadastros, tags e leituras continuam no banco. O teste de interface confirma
a alternância e a atualização dos indicadores junto com a tabela.
