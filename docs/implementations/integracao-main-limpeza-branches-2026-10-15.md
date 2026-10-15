# Integração da main e limpeza de branches — 15/10/2026

## Problema e importância para o MVP

Os PRs #72, #73, #75 e #77 foram integrados à `main`, mas o PR #81 ainda
usava `feat/iss-025-correcao-manual` como base. A reescrita anterior da pilha
deixou conflitos e branches locais com hashes antigos. A manutenção permite
continuar o desenvolvimento a partir de uma base comum com as telas de
administração integradas aos recursos existentes.

## Resolução

- A `main` local foi atualizada por fast-forward até `efac17b`.
- A `main` foi incorporada ao PR #81 e sua base foi alterada para `main`.
- Foram resolvidos nove arquivos em conflito: índice de documentação, guias
  das ISS-025 e ISS-028, App, AppShell, troca de senha, estilos, testes de
  autenticação e configuração do Vite.
- Foram preservados a atualização automática, o painel de correção manual,
  as permissões da sessão e os proxies existentes. O diff contra a base
  contém somente frontend e documentação, sem mudanças no backend ou schema.
- As branches remotas `feat/iss-025-correcao-manual`,
  `feat/iss-026-usuarios-autenticacao`, `feat/iss-027-perfis-rbac`,
  `feat/iss-028-auditoria` e `fix/iss-006-final-sync` foram removidas após
  confirmar seus PRs integrados (#77, #72, #73, #75 e #52).
- As quatro branches locais antigas das ISS-025 a ISS-028 também foram
  removidas. Antes da limpeza, um bundle completo de branches e referências
  remotas foi criado e verificado em `.git/branch-backups/`, fora dos arquivos
  versionados. As cópias de trabalho e arquivos locais foram preservados.

## Verificações antes da integração

Passaram os 58 testes do frontend, o build TypeScript/Vite, Ruff
(`E4,E7,E9,F,I`) e `git diff --check`. Não restaram marcadores de conflito.
Em PostgreSQL 16 descartável local, `alembic -c config/alembic.ini upgrade head` e `alembic check`
passaram sem diferenças de schema. Nenhum banco compartilhado foi alterado.

Estes resultados validam software em ambiente sintético; o aceite físico do
EZ700 e da rede hospitalar continua pendente.
