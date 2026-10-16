# Como documentar uma mudança

Este guia diz onde cada tipo de informação vai e o que conferir antes de abrir
um PR. A regra de base está no [`AGENTS.md`](../AGENTS.md): toda issue
implementada deixa um `.md` explicando o que é, por que importa para o MVP e o
que foi feito.

## Onde cada coisa vai

| O que mudou | Onde registrar | Modelo |
|---|---|---|
| Comportamento de módulo, classe ou função | Docstring em português, no próprio código | — |
| Issue implementada | `docs/implementations/iss-NNN-tema.md` | [registro de issue](templates/registro-issue.md) |
| Correção pontual | `docs/implementations/hotfix-tema.md` | [registro de issue](templates/registro-issue.md) |
| Decisão com alternativas descartadas ou limites assumidos | `docs/decisions/NNNN-tema.md` e linha no índice | [ADR](templates/adr.md) |
| Tabela, coluna, índice ou constraint | `docs/architecture/data-model.md` e `er-diagrama.mermaid` | — |
| Fluxo, parâmetro ou arquitetura | `docs/architecture/system-overview.md` | — |
| Comando, perfil de ambiente ou procedimento | `docs/operations/` | — |
| Ensaio, medição ou evidência | `docs/experiments/` | — |

## Antes de abrir o PR

1. Docstrings atualizadas: `python scripts/documentation.py --check`.
2. Registro da issue criado, seguindo o modelo.
3. Registro adicionado ao índice em [`docs/README.md`](README.md), na tabela
   "Problemas e soluções". Um registro fora do índice não é encontrado.
4. ADR criado, se a decisão tem alternativas descartadas.
5. Schema alterado: modelo de dados e diagrama ER atualizados na mesma mudança.
6. Tabelas geradas regeneradas por script (por exemplo
   `python -m tools.tabela_permissoes`), nunca editadas à mão.
7. Links relativos conferidos e nenhuma credencial, token ou senha nos exemplos.

## Convenções

- Português, com frases curtas e sem jargão desnecessário.
- Nome de arquivo em minúsculas e com hífens: `iss-029-tema.md`.
- Diga sempre o nível da evidência: **simulação**, **teste de integração** ou
  **validação física**. Simulação não prova comportamento do hardware.
- Registros históricos conservam o resultado da sua data. Para o comando atual,
  vale o guia em `docs/operations/`.
- Notas pessoais e documentos internos ficam em `data/private-docs/`, ignorado
  pelo Git, sem link na documentação pública.
