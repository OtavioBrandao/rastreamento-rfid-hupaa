# Migrations — comandos, convenções e rollback (ISS-002c)

Documento de apoio à ISS-002c (Épico E1, Must, RNF-011, RNF-012, RNF-016). Complementa `docs/decisions/0003-modelagem-dados.md` (decisões de modelagem) e `docs/database/neon-setup.md` (infraestrutura do banco).

## 1. Comandos padronizados

Todos assumem `DATABASE_URL` já definida (via `.env` local ou exportada na sessão) e ambiente virtual ativado.

| Ação | Comando |
|---|---|
| **Aplicar** todas as migrations pendentes | `python -m alembic upgrade head` |
| **Verificar** a versão atual do banco | `python -m alembic current` |
| **Verificar** o histórico completo de migrations | `python -m alembic history` |
| **Reverter** a última migration | `python -m alembic downgrade -1` |
| **Reverter** tudo (banco volta a vazio) | `python -m alembic downgrade base` |
| **Criar** uma migration nova a partir de mudanças em `db/models.py` | `python -m alembic revision --autogenerate -m "descrição da mudança"` |

**Um banco vazio chega ao schema atual com um único comando**: `python -m alembic upgrade head` (critério de aceitação da issue — validado em banco local e em branch de teste do Neon).

## 2. Convenção para novas migrations

1. Alterar `db/models.py` primeiro (é a fonte da verdade do schema).
2. Gerar a migration com `--autogenerate`, **nunca escrever à mão** — reduz risco de divergência entre o que o SQLAlchemy espera e o que o banco realmente tem.
3. **Sempre revisar o arquivo gerado antes de commitar.** O autogenerate do Alembic não captura tudo de forma confiável (ex.: `CHECK` constraints às vezes precisam de conferência manual — foi o caso da constraint de período válido da ISS-002a).
4. Testar localmente **os dois sentidos** antes de abrir PR: `upgrade head` e `downgrade` de volta à revisão anterior.
5. Mensagem da migration: curta, descritiva, em português, minúsculo (ex.: `"adiciona coluna status em leitores"`, não `"fix"` ou `"update"`).
6. **Nunca editar uma migration que já foi aplicada em qualquer ambiente compartilhado** (Neon principal, ou que outro integrante da dupla já rodou). Se precisar corrigir algo depois de aplicado, cria uma migration **nova** por cima — migrations são append-only depois de compartilhadas. Editar uma já aplicada quebra a sincronia entre bancos que já rodaram a versão antiga e os que ainda vão rodar.
   - Exceção: enquanto a migration só existir **localmente**, sem ter sido aplicada em nenhum ambiente compartilhado (Neon principal ou do outro integrante) — nesse caso, apagar e regenerar é seguro. Foi o que fizemos na ISS-002a depois da revisão do Otávio, antes do merge.
7. **Revisão em Pull Request:** toda migration nova passa por review da dupla antes do merge — mesmo padrão já usado na ISS-002a (duas rodadas de revisão de código do Otávio pegaram problemas reais: idempotência do `event_id`, semântica temporal de `associacoes_tag_equipamento`, bug de `%` em `DATABASE_URL`). O CI (seção 4) roda automaticamente em todo PR que toque `db/`, `alembic/` ou `alembic.ini`.

## 3. Rollback / procedimento de correção segura

### Cenário A — Migration ainda só local, nunca aplicada em ambiente compartilhado
Seguro apagar o arquivo e regenerar via `--autogenerate` depois de corrigir `db/models.py`. Foi o fluxo usado na ISS-002a.

### Cenário B — Erro descoberto ANTES de aplicar no Neon principal (só em banco local/branch de teste)
```bash
python -m alembic downgrade base   # limpa o banco de teste
# corrige db/models.py
rm alembic/versions/<arquivo_com_erro>.py
python -m alembic revision --autogenerate -m "schema inicial"
python -m alembic upgrade head     # reaplica, já corrigido
```

### Cenário C — Erro descoberto DEPOIS de já ter aplicado no Neon principal (produção)
**Nunca editar a migration já aplicada.** Duas opções, dependendo da gravidade:

1. **Correção incremental (preferida):** criar uma migration nova que ajusta o que está errado (ex.: `ALTER TABLE ... ADD CONSTRAINT ...`). Mantém o histórico rastreável e não exige coordenar downtime com a dupla.
2. **Rollback completo (emergência):** só quando a correção incremental não for viável.
```bash
   python -m alembic downgrade base
   # corrigir db/models.py e a migration
   python -m alembic upgrade head
```
   **Antes de rodar isso contra o Neon principal:** avisar a outra pessoa da dupla (evita ela rodar algo no meio do processo), e testar a correção numa **branch de teste do Neon** primeiro (`neonctl branches create --name teste-rollback --parent main`) — nunca testar uma correção de emergência direto em produção.

### Incidente real documentado (referência)
A ISS-002b registra um incidente onde a migration antiga foi aplicada por engano no Neon principal (ambiente local desatualizado — `git pull` da `main` mergeada não tinha sido feito). Resolvido com o fluxo do Cenário C, opção 2 (rollback completo, já que o schema errado tinha acabado de ser criado, sem dados reais ainda). Detalhes completos em `docs/database/neon-setup.md`, seção 8. **Lição geral:** sempre conferir `git log --oneline -5` e o ID da migration esperado antes de rodar `upgrade head` contra o banco principal.

## 4. Verificação no CI

Workflow em `.github/workflows/migrations.yml` — roda em todo PR/push que toque `db/`, `alembic/` ou `alembic.ini`. Sobe um Postgres descartável (serviço do GitHub Actions, não é o Neon), e:
1. Aplica todas as migrations em banco vazio (`upgrade head`)
2. Roda `upgrade head` de novo, confirmando que não duplica/corrompe
3. Reverte tudo (`downgrade base`)
4. Reaplica (`upgrade head`) — confirma que o rollback é reversível
5. Confirma a contagem exata de tabelas (17: 16 do domínio + `alembic_version`)
6. Roda a suíte de testes (`pytest tests/`, incluindo `test_database_url.py`)

Se qualquer um desses passos falhar, o PR fica com o check vermelho — é isso que cumpre o critério "CI detecta migration inválida ou schema que não sobe".
