# ISS-028 — Trilha de auditoria imutável (issue #30)

## O que é e por que importa

Até a ISS-027 a tabela `auditorias` só recebia linhas de dois serviços (usuários e vínculo de EPC), gravadas à mão, em inglês (`create`/`update`/`delete`) e sem proteção contra edição. Para o HUPAA, quem mudou o cadastro de um equipamento, de uma zona ou de um leitor, e quando, precisa ter resposta confiável: uma trilha incompleta ou editável não serve como evidência.

Esta issue entrega:

- **registro central automático** de toda mudança nas tabelas de cadastro, sem chamada espalhada pelos serviços;
- **eventos de segurança** na mesma trilha: login aceito e recusado, bloqueio, logout e acesso negado;
- **imutabilidade garantida pelo banco**: um trigger recusa `UPDATE` e `DELETE`;
- **consulta só pela API** (`GET /auditorias`, administrador). Não há tela.

## Catálogo de ações (e quem gera cada uma)

| Ação | Quando | Quem gera |
|---|---|---|
| `criar` | linha nova numa tabela auditada | registro central |
| `atualizar` | mudança de campo auditável sem regra mais específica | registro central |
| `inativar` / `reativar` | `ativo` mudou; `status` de equipamento mudou; `fim` de mapeamento preenchido (`inativar`) | registro central |
| `excluir` | `DELETE` pelo ORM (estado completo em `dados_antes`) | registro central |
| `vincular_epc` | associação tag ↔ equipamento criada (com o EPC) | registro central |
| `desvincular_epc` | `fim` da associação preenchido (com o EPC antes e depois) | registro central |
| `alterar_senha` | `senha_hash` mudou (troca pelo titular ou redefinição por admin) | registro central |
| `correcao_manual` | herdada do vocabulário anterior | — |
| `login_aceito` | login com sucesso | `service_auth` |
| `login_recusado` | qualquer login recusado (motivo interno no campo `motivo`) | `service_auth` |
| `conta_bloqueada` | N falhas seguidas no login (`tentativas_de_login`) ou na troca de senha (`tentativas_de_troca_de_senha`) | `service_auth` |
| `logout` | sessão encerrada pelo titular | `service_auth` |
| `acesso_negado` | 403 de permissão (`entidade = 'rota'`, dados com permissão, método e molde da rota) | `api/permissoes.py` |

Tabelas auditadas: `tipos_equipamento`, `equipamentos`, `associacoes_tag_equipamento`, `andares`, `setores`, `zonas`, `leitores`, `antenas`, `portais`, `mapeamentos_antena_portal` e `usuarios`.

## Origem e autor

| `origem` | `usuario_id` | Quando |
|---|---|---|
| `usuario` | id do usuário da sessão | mudança feita por request autenticada; `login_aceito`; `logout`; `acesso_negado`; bloqueio na troca de senha |
| `sistema` | NULL | processo sem autor: comando de terminal (`criar_admin`, com `motivo`), scripts, ORM direto |
| `anonimo` | NULL | tentativa sem sessão: `login_recusado` e `conta_bloqueada` do login (o alvo vai em `entidade_id`, se existir) |

O CHECK `ck_auditoria_autor_coerente` garante no banco que `origem = 'usuario'` se e somente se houver `usuario_id`.

## O que entra (e o que não entra) em `dados_antes`/`dados_depois`

- **Criar**: estado completo em `dados_depois`. A associação leva o `epc`; o usuário leva o nome do `perfil`.
- **Alterar**: **só os campos que mudaram**, a partir do histórico de atributo do ORM. Sem mudança auditável, nenhuma linha: um PATCH com os mesmos valores ou um login que só mexe no contador de falhas não geram ruído. A associação leva o `epc` em antes e depois; a troca de perfil leva o nome do perfil antigo e do novo.
- **Excluir**: estado completo em `dados_antes`.
- **Nunca entram**:
  - em todas as tabelas: `id`, `created_at`, `updated_at` e qualquer coluna `*_normalizado`;
  - em `usuarios`: `senha_hash`, `tentativas_falhas`, `bloqueado_ate` e `ultimo_login_em`;
  - em `equipamentos`: a projeção de localização (`ultima_zona_id`, `ultima_deteccao_em`, `ultima_passagem_id`, `ultima_movimentacao_id`);
  - em `leitores`: `status` e `ultimo_heartbeat_em`.
- **Senha**: se `senha_hash` mudou, a trilha registra só `"senha": "alterada"` em `dados_depois`, nunca o valor. O e-mail digitado num login de conta inexistente também não é gravado: é comum digitarem a senha nesse campo.

## Como funciona

- **Listener `after_flush`** na classe `Session` (`api/auditoria.py`), ativo para toda sessão do processo que importe o pacote `api` (o import está em `api/__init__.py`).
  - Ele percorre `db.new`, `db.dirty` (só o que `db.is_modified`) e `db.deleted` das tabelas auditadas, monta as linhas em `linhas_do_flush` e as insere por **SQL Core** em `db.connection()`.
  - As linhas ficam na mesma transação da mudança: se o commit falhar, a trilha some junto; se a trilha falhar, a mudança não é gravada.
  - Um `before_flush` carrega o estado dos objetos excluídos antes do `DELETE`.
- **Histórico ativo**: cada coluna dos modelos auditados tem um listener `set` com `active_history=True`. Sem ele, atribuir a um atributo **expirado** (depois de um commit na mesma sessão) não carregaria o valor antigo, e a trilha gravaria `antes = None`.
- **Contexto de cada linha**:
  - autor: `definir_autor(db, usuario_id)`, chamado por `sessao_autenticada` em toda request autenticada;
  - motivo: `definir_motivo(db, texto)`;
  - correlação: a `ContextVar` `correlacao_da_requisicao`; fora de HTTP, um uuid4 por sessão do banco.
- **Middleware HTTP** (`api/main.py`): lê `X-Correlation-ID`, aceita o valor se casar com `^[A-Za-z0-9._-]{1,64}$` e senão gera um uuid4 hex. O mesmo valor volta no header de **toda** resposta, inclusive 401, 403 e 422, e vai para toda linha da trilha gerada pela request. Uma troca de EPC, por exemplo, gera `desvincular_epc` e `vincular_epc` com o mesmo id.
- **Eventos explícitos**: `registrar(db, acao, *, entidade, ...)` adiciona a linha pela ORM, sem commit, na transação do chamador.

A auditoria explícita antiga foi removida de `service_associacao`, `service_usuarios` e `criar_admin`.

## Imutabilidade

O trigger `tg_auditorias_append_only` (`BEFORE UPDATE OR DELETE ... FOR EACH ROW`) chama `auditorias_append_only()`, que falha com `insufficient_privilege` e a mensagem "auditorias é append-only: UPDATE/DELETE não é permitido". Vale para a aplicação, para `psql` e para qualquer papel.

- **TRUNCATE** não dispara trigger de linha e esvazia a tabela. É privilégio do **dono** da tabela, por isso o papel usado pela aplicação (ex.: no Neon) **não deve** ser o dono nem ter `TRUNCATE` em `auditorias`. Os testes usam TRUNCATE em banco descartável, e só ali.
- Como a trilha referencia `usuarios`, um usuário que já agiu (ou que tentou logar) **não pode mais ser apagado fisicamente**. A baixa de usuário já era lógica (`ativo = false`).

## Consulta `/auditorias`

Exige `auditoria:consultar`, que só o administrador tem ([matriz da ISS-027](iss-027-perfis-rbac.md)). Não há rota de escrita.

- `GET /auditorias`:
  - filtros combinados por AND: `entidade`, `entidade_id`, `acao` (só valores do catálogo), `origem`, `usuario_id` e `correlation_id`;
  - `desde` (inclusivo) e `ate` (exclusivo), os dois **com fuso**; sem fuso, 422;
  - `page` ≥ 1 e `size` de 1 a 200 (padrão 50);
  - ordem: `registrado_em` desc, depois `id` desc;
  - resposta `{items, page, size, total, pages}`, e cada item traz `usuario_nome` (outer join com `usuarios`).
- `GET /auditorias/{id}`: o registro, ou 404.

## Migration `e028a1b2c3d4` (filha de `d026a1b2c3d4`)

**Upgrade:**
- traduz a trilha legada (`create`→`criar`, `update`→`atualizar`, `delete`→`excluir`) e recria o CHECK com o catálogo;
- cria `origem`, preenchida com `sistema` sem autor e `usuario` com autor, depois NOT NULL, com os CHECKs de origem e de coerência do autor;
- cria `correlation_id` e `motivo`, torna `entidade_id` anulável e cria os três índices;
- cria a função e o trigger.

**Downgrade:**
1. Remove o trigger e a função.
2. **Recusa** (`RuntimeError` "downgrade recusado", com as contagens) se houver linhas sem `entidade_id` ou com ação sem equivalente no vocabulário antigo. O schema antigo não comporta essas linhas, e trilha não se apaga. Como o DDL do Postgres é transacional, a recusa desfaz tudo e o trigger continua lá.
3. Sem recusa, guarda `motivo` e `correlation_id` em `dados_depois` sob a chave `_iss028` (`jsonb_strip_nulls`, só nas linhas que tenham algum dos dois).
4. Reverte índices, colunas, CHECKs e o vocabulário antigo.

## Testes e evidências

- **`tests/test_auditoria.py`** (login e cookie reais):
  - completude pela API, com autor, origem `usuario` e `correlation_id` igual ao header em cada linha: tipos, equipamentos, vínculo, troca e desvínculo de EPC, andar, setor, zonas, leitor sem `status`, portal, antena, mapeamento e inativar/reativar;
  - ausência de ruído: PATCH sem mudança e login não geram linha de cadastro;
  - ORM direto: valor antigo real de atributo expirado, mesmo valor sem linha, `excluir` com estado completo;
  - eventos de segurança, e N falhas gerando N recusas e um bloqueio;
  - varredura da tabela inteira atrás de senhas, hashes, `token_hash`, `$argon2`, `senha_hash` e e-mail digitado;
  - imutabilidade e atomicidade (falha na trilha desfaz a operação);
  - consulta: filtros, paginação, ordem, `usuario_nome`, `desde`/`ate`, 422, 404, 401 e 403;
  - correlação: id do cliente aceito, id malformado trocado, header em toda resposta.
- **`tests/test_migration_iss028.py`** (banco descartável): legado traduzido, origem e trigger; os CHECKs disparando; downgrade e reupgrade com `alembic check`; downgrade recusado com a trilha e o trigger intactos; preservação em `_iss028`.
- Testes existentes ajustados ao vocabulário novo (usuários, associação, `criar_admin`, matriz RBAC e head da migration). Também foi corrigido o teste intermitente de hash truncado em `test_auth_config.py`.
- Smoke com uvicorn: admin por `criar_admin`, login, criação de tipo com `X-Correlation-ID: smoke-028`, login falho e consulta por `correlation_id`. Varredura da tabela e do log sem nenhuma senha nem o token do cookie.

## Limites

- **O pipeline de ingestão e inferência não é auditado aqui**: escreve por SQLAlchemy Core (passagens, histórico, projeção da última zona), sem passar pelo ORM. A ISS-018 cobre a movimentação com seu ledger próprio.
- **O seed do laboratório** (`tools/lab_launcher/seed.py`) importa o pacote `api` e usa os serviços de cadastro: ele **é** auditado, com origem `sistema` e sem autor (não há sessão HTTP); o seed não escreve por SQL direto.
- **SQL direto** (`psql`, scripts com `text(...)`) não passa pelo listener e não é auditado. O trigger impede adulterar a trilha, mas não registra o que não passou pelo ORM.
- **Testes com sessão simulada** (o administrador transiente do `conftest`, sem linha no banco) gravam origem `sistema`: o autor só é definido pela `sessao_autenticada` real.
- **Não há tela, exportação nem política de retenção** da trilha.
