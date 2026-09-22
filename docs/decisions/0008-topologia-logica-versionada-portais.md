# ADR 0008 — Topologia Lógica Versionada de Portais

## Status
Aceito e implementado (ISS-013)

## Contexto
Na ISS-012, foi modelada a topologia física de hardware: leitores possuem portas físicas conectadas a antenas, e antenas podem opcionalmente estar associadas a um portal (`antenas.portal_id`).

Entretanto, para que o motor de inferência de passagens e direções (ISS-015) determine se um equipamento realizou uma passagem $A \rightarrow B$ ou $B \rightarrow A$, é necessário responder:
*"Qual é o significado lógico e operacional de cada antena dentro daquele portal?"*

Isso envolve:
1. Em qual lado do portal a antena está apontada (Lado A ou Lado B)?
2. Qual a zona adjacente correspondente a esse lado?
3. Qual a função operacional da antena naquela passagem (`entrada`, `saida`, `auxiliar`)?

Se essa configuração fosse resolvida apenas adicionando uma coluna mutável `lado` na tabela `antenas`:
- A qualquer momento em que uma antena fosse reconfigurada fisicamente (ex.: invertida de lado, realocada para outro portal ou tendo sua zona alterada), a atualização sobrescreveria os valores anteriores.
- Leituras brutas passadas (`leituras_brutas`) e passagens históricas (`passagens`) perderiam a rastreabilidade retrospectiva, tornando impossível reinterpretar eventos passados com exatidão temporal.

## Decisão
1. **Preservação do Hardware Atual vs. Topologia Lógica Temporal:**
   - As colunas de `Antena` e `Portal` da ISS-012 permanecem como representação do **estado físico/hardware atual**.
   - Cria-se uma entidade dedicada `MapeamentoAntenaPortal` (`mapeamentos_antena_portal`), que registra a configuração lógica e direcional em intervalos temporais semiabertos `[inicio, fim)`.

2. **Semântica Temporal:**
   - `fim IS NULL` indica o mapeamento atualmente ativo/vigente.
   - Qualquer substituição ou reconfiguração encerra o registro anterior (`fim = now()`) e cria um novo (`inicio = now()`, `fim = NULL`) em uma única transação atômica.
   - Registros anteriores permanecem imutáveis para consulta histórica.

3. **Unicidade de Antena Ativa e Suporte a Múltiplas Antenas:**
   - No nível de banco de dados, o índice único parcial:
     ```sql
     CREATE UNIQUE INDEX uq_mapeamento_antena_ativo
     ON mapeamentos_antena_portal (antena_id)
     WHERE fim IS NULL;
     ```
     garante que uma antena física possui no máximo **um** mapeamento lógico ativo simultâneo.
   - Não se aplica unicidade sobre `(portal_id, lado)`, permitindo explicitamente múltiplas antenas no mesmo lado do portal (ex.: duas antenas no Lado A e duas no Lado B).

4. **Invariantes e Coerência de Zonas:**
   - Lado A exige estritamente `zona_id == portal.zona_a_id`.
   - Lado B exige estritamente `zona_id == portal.zona_b_id`.
   - Funções são restritas a `entrada`, `saida` ou `auxiliar` (rejeitando `indefinido` em mapeamentos ativos).
   - Guards bloqueiam mutação das zonas do portal ou do `portal_id`/`zona_associada_id` da antena enquanto houver mapeamento ativo associado.

## Alternativas Consideradas
- **Colunas mutáveis diretas em `antenas`:** Rejeitada, pois destruiria o histórico e violaria o requisito de auditoria e interpretação determinística de leituras passadas.
- **SCD Tipo 2 completo em todas as entidades de hardware:** Rejeitada por gerar complexidade desnecessária sobre leitores e portas físicas, que são ativos inventariados e não regras de negócio temporais.
- **Restrição de exclusão temporal via `btree_gist` (`EXCLUDE`):** Postergada para manter consistência com `AssociacaoTagEquipamento` (ADR 0003), delegando a garantia de não-sobreposição à camada de serviço nesta etapa do MVP.

## Consequências
- A inferência de direção na ISS-015 pode consultar a topologia do portal em uma única rota/query sem ambiguidades.
- A substituição física ou reconfiguração de antenas preserva integralmente a interpretação retrospectiva de passagens já registradas.
- Alterações inadvertidas nas zonas de um portal com antenas ativas são prevenidas por guards de domínio (HTTP 409).
