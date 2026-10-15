# Revisão dos PRs do Thiego — 14/10/2026

## Escopo e resultado

Revisados os quatro PRs abertos do autor `Thieg0`, seus diffs incrementais,
dependências, migrations, testes e integração com a `main` atual.
Não foram identificados defeitos bloqueantes nos heads abaixo. São aptos à
aprovação técnica no escopo experimental do MVP, respeitando a ordem de merge.
Esta revisão não executou merge nem publicou novas avaliações no GitHub.

| PR | Head revisado | Parecer | Frontend existente |
|---|---|---|---|
| [#72 — ISS-026](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/pull/72) | `af1cc2e` | Apto; integrar junto da proteção da ISS-027 antes de disponibilizar a aplicação | Administração de usuários ausente |
| [#73 — ISS-027](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/pull/73) | `acc4707` | Apto após #72; objeção anterior resolvida | Login, troca obrigatória de senha, sessão e perfil |
| [#75 — ISS-028](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/pull/75) | `b6cf1b0` | Apto após #73 | Consulta da auditoria ausente |
| [#77 — ISS-025](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/pull/77) | `66d442a` | Apto após #75; objeção anterior resolvida | Correção manual de cadastro e localização, com revisão e conflito |

Ordem: **#72 → #73 → #75 → #77 → complemento de frontend**.
Os quatro PRs estavam `MERGEABLE`/`CLEAN` e com CI verde na consulta.
As avaliações antigas `CHANGES_REQUESTED` em #73 e #77 ainda existem no
GitHub; precisam ser substituídas ou dispensadas pelo fluxo de revisão do
repositório. Isso é uma pendência de aprovação formal, não um defeito pendente
nos commits atuais.

## Objeções anteriores verificadas

- **#73:** `/api/leituras/resumo` exige `laboratorio:consultar`, usando a
  mesma barreira de sessão/permissão das demais rotas. O teste por introspecção
  inclui as rotas presentes na aplicação, e a matriz passou no banco real.
- **#77:** `EquipmentDrawer` carrega `/api/ativos/{id}` pelo ID estável e usa
  a atualização global após a correção. Não depende mais da primeira página
  de uma busca parcial pelo patrimônio. Os testes atuais incluem a identidade
  estável e a atualização do detalhe.
- A `main` `324a32c`, com Leituras, atualização automática e mapas, já está
  integrada à pilha; o merge local no head #77 informou `Already up to date`.

## Pontos conferidos

- Sessões opacas, persistência somente do hash, cookie HttpOnly/Secure/SameSite,
  revogação, senha temporária e sanitização dos erros de validação.
- Bloqueio por conta e ordenação dos locks da administração; proteção do último
  administrador e revalidação do autor depois de esperar pelo lock.
- Permissões negadas por padrão e proteção das rotas do backend, inclusive
  leituras; o frontend consome permissões da sessão.
- Auditoria central do ORM, exclusão de segredos/ruído, atomicidade, trigger
  contra UPDATE/DELETE, correlação e consulta exclusiva de administrador.
- Preservação/recusa nos downgrades da auditoria e checks das novas migrations.
- Correções com justificativa, versão otimista, histórico append-only,
  atualização transacional da localização e preservação da recência.

## Evidências e limites

Executada a suíte acumulada no head #77 em PostgreSQL 16 local descartável:
**1.303 testes e 93 subtestes passaram, 5 pulados** (integrações opcionais
MQTT/OpenSSL). Ruff passou e `alembic check` ficou sem alterações. No frontend
original da pilha, os 42 testes passaram; com as telas complementares, são 58.
Os checks de CI dos PRs individuais também estavam aprovados.

Os testes locais são da pilha acumulada, não quatro execuções isoladas por PR.
Não foi usado o banco remoto, e esta revisão não constitui validação física.
A ISS-026 isolada deixa rotas de negócio públicas por decisão de escopo;
disponibilizar a aplicação somente depois da ISS-027.

As interfaces ausentes foram implementadas em
[ISS-026 / ISS-028 — Frontend de administração](iss-026-028-frontend-administracao.md),
com documentação e evidências de software em português.
