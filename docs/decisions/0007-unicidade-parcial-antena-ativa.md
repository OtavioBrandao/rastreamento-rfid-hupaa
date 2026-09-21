# ADR 0007 — Unicidade Parcial de Antena Ativa e Preservação Histórica

## Status
Aceito e implementado (ISS-012)

## Contexto
Um leitor RFID possui portas físicas numeradas (ex.: portas 1 a 4). Fisicamente, apenas um cabo coaxial de antena pode estar conectado a uma porta em um dado momento.

No entanto, no ciclo de vida de manutenção de um hospital:
1. Uma antena pode sofrer avaria ou ser substituída por outro modelo com ganho diferente.
2. Se a antena antiga fosse removida do banco via `DELETE`, a integridade referencial seria violada, pois dezenas de milhares de leituras passadas em `leituras_brutas.antena_id` e passagens históricas apontam para ela.
3. Se a constraint no banco fosse `UNIQUE (leitor_id, porta_numero)`, a substituição seria bloqueada: o banco impediria cadastrar uma nova antena na porta 1 enquanto a antena antiga continuasse existindo no banco de dados.

## Decisão
1. **Baixa Lógica para Hardware:** Leitores, antenas e portais utilizam ciclo de vida administrativo com `ativo = true/false`, nunca sofrerão `DELETE` físico se houver referências.
2. **Índice Único Parcial:** Implementar no PostgreSQL um índice condicional estrito:
   ```sql
   CREATE UNIQUE INDEX uq_antena_ativa_por_porta_leitor
   ON antenas (leitor_id, porta_numero)
   WHERE ativo IS TRUE;
   ```
3. **Resolução de Ingestão:** O repositório de persistência (`RawReadingRepository`) busca a antena usando obrigatoriamente:
   ```python
   select(Antena.id).where(
       Antena.leitor_id == leitor_id,
       Antena.porta_numero == porta_numero,
       Antena.ativo.is_(True),
   )
   ```

## Consequências
- Cada porta física de um leitor pode ter no máximo **uma** antena ativa simultaneamente.
- Uma antena com defeito pode ser desativada (`ativo = false`), liberando imediatamente a porta física para que uma nova antena ativa seja associada.
- O histórico de leituras brutas permanece íntegro, referenciando a antena que estava de fato operando no momento de cada leitura.
- Reativações acidentais de antenas antigas em portas que já foram ocupadas por outras antenas ativas são bloqueadas diretamente no nível de banco de dados (HTTP 409).
