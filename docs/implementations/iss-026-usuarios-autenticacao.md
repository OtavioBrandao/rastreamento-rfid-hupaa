# ISS-026 — Cadastro, autenticação e administração de usuários (issue #28)

## O que é a issue

Até aqui a API do MVP era aberta: as tabelas `usuarios`, `perfis` e `auditorias` existiam desde o schema inicial, mas nada as usava, `perfis` estava vazia e nenhuma rota exigia login. Esta issue entrega:

- login por e-mail e senha com sessão em cookie, logout, consulta da sessão e troca de senha (`/auth`);
- administração de usuários por administradores (`/usuarios`);
- criação do primeiro administrador pelo terminal (`python -m api.criar_admin`).

**Fora do escopo, de propósito:** proteger as rotas existentes (equipamentos, zonas, hardware etc.) é a ISS-027, e o catálogo de auditoria é a ISS-028. Essas rotas continuaram públicas até a [ISS-027](iss-027-perfis-rbac.md), que as protegeu.

## Por que importa para o MVP

A localização de equipamentos do HUPAA não pode ser consultada nem alterada por qualquer pessoa na rede do hospital. Antes de restringir as rotas (ISS-027), o sistema precisa saber **quem** está usando e precisa **encerrar esse acesso na hora** quando alguém sai da equipe, troca de função ou perde a senha. A decisão e as alternativas estão no [ADR 0009](../decisions/0009-autenticacao-sessao-opaca-cookie.md).

## Contrato HTTP

### `/auth`

| Rota | Sessão | Sucesso | Erros |
|---|---|---|---|
| `POST /auth/login` `{email, senha}` | — | 200 `{usuario, sessao_expira_em}` + cookie | 401 `credenciais_invalidas` (sempre igual); 422 só por tamanho ou tipo |
| `POST /auth/logout` | opcional | 204 + cookie apagado | — (idempotente) |
| `GET /auth/me` | qualquer válida | 200 `{usuario, sessao_expira_em}` | 401 `nao_autenticado` |
| `POST /auth/trocar-senha` `{senha_atual, nova_senha}` | qualquer válida | 204 | 400 `senha_atual_incorreta`; 422 `nova_senha_igual_a_atual` ou senha fora da política; 401 |

- **Cookie** `rfid_sessao`: `HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=<duração>`. O token vai **só** no cookie; o header `Authorization` é ignorado.
- **Login recusado** devolve o mesmo 401, com a mesma mensagem e sem cookie, para senha errada, conta inexistente, inativa ou bloqueada. Os quatro casos executam exatamente **uma** verificação Argon2 completa (hash fictício quando a conta não existe).
- O body de login **só limita tamanho** (e-mail ≤ 320, senha ≤ 1024). Validar o formato do e-mail ali devolveria 422 para um e-mail e 401 para outro, e essa diferença vazaria informação.
- **Senha temporária**: a sessão só acessa `/auth/me`, `/auth/trocar-senha` e `/auth/logout`. As rotas autenticadas restantes (hoje, todo `/usuarios`) respondem 403 com detail exatamente `troca_de_senha_obrigatoria`, valor de que o front da ISS-027 vai depender.
- **Troca de senha**: exige a senha atual, e errá-la conta como falha de login (pode bloquear a conta). Recusa nova senha igual à atual. Derruba as **outras** sessões e mantém a atual.

### `/usuarios` (todas exigem administrador com sessão liberada)

| Rota | Resposta | Regras |
|---|---|---|
| `GET /usuarios?page&size&ativo&perfil` | 200 `{items, page, size, total, pages}` | mesmo formato do ledger de movimentações; ordem por id |
| `POST /usuarios` `{nome, email, perfil, senha_temporaria}` | 201 | `deve_trocar_senha=true`; 409 e-mail duplicado (comparação já normalizada) |
| `GET /usuarios/{id}` | 200 | 404 |
| `PATCH /usuarios/{id}` `{nome?, perfil?}` | 200 | e-mail **não** editável: campo extra → 422; 409 ao rebaixar o último admin ativo |
| `POST /usuarios/{id}/desativar` | 200 | revoga as sessões do alvo; 409 na própria conta |
| `POST /usuarios/{id}/reativar` | 200 | zera o bloqueio; **não** ressuscita sessões antigas |
| `POST /usuarios/{id}/redefinir-senha` `{senha_temporaria}` | 200 | `deve_trocar_senha=true`, zera o bloqueio, revoga sessões; 409 na própria conta |

Sem sessão → 401 `nao_autenticado`; perfil operacional → 403 `acesso_negado` (detail unificado na [ISS-027](iss-027-perfis-rbac.md); antes era `acesso_restrito_a_administradores`); admin com senha temporária → 403 `troca_de_senha_obrigatoria`. Nenhum schema de resposta tem campo de senha ou hash.

A resposta de usuário traz `id, nome, email, perfil, ativo, deve_trocar_senha, bloqueado_ate, ultimo_login_em, created_at, updated_at`, com instantes em UTC.

**Política de senha** (nova senha, senha temporária e comando de terminal): de 8 a 128 caracteres, não só espaços. A mensagem de recusa nunca ecoa a senha.

**E-mail na criação**: normalizado (`strip().lower()`) e restrito a ASCII no formato `nome@dominio.tld`. Para ASCII, a normalização do Python e a CHECK do Postgres (`lower(btrim())`) coincidem exatamente.

### 422 sem eco de senha

O handler de 422 de `api/main.py` já removia `input`/`ctx` dos erros de `parametros_ingestao`. Agora também remove dos erros cujo `loc` contém `senha`, `senha_atual`, `nova_senha` ou `senha_temporaria`, **e** dos erros cujo `input` é um objeto que contém algum desses campos. O segundo caso cobre o erro de campo ausente, em que o Pydantic devolve o corpo inteiro (com a senha) como `input`.

## Primeiro administrador

```bash
set -a; source .env.local; set +a
python -m alembic upgrade head
python -m api.criar_admin --nome "Fulana de Tal" --email fulana@hupaa.example
# Senha: (getpass)  Repita a senha: (getpass)

# Automação (CI, script de provisionamento):
printf '%s\n' "$SENHA_ADMIN" | python -m api.criar_admin --nome ... --email ... --senha-stdin
```

No PowerShell, ou sem exportar variáveis no shell, use o arquivo explicitamente:

```powershell
.\.venv\Scripts\python.exe -m api.criar_admin --env-file .env.cloud --nome "Seu Nome" --email "seu@email.com"
```

`--env-file` aceita também `.env.local` e caminhos absolutos. As variáveis do
arquivo explícito prevalecem sobre o ambiente do terminal. Sem a opção, continuam
valendo as variáveis exportadas e o `.env` padrão; não há seleção automática de
banco remoto. Arquivo inexistente ou `DATABASE_URL` ausente gera uma mensagem
orientativa antes de pedir a senha. Veja o [hotfix](hotfix-criar-admin-env-file.md).

- A senha nunca vai em argumento de linha de comando: ficaria no histórico do shell e visível em `ps`. Não existe opção `--senha`.
- O comando recusa rodar se já houver administrador ativo; `--recuperacao` libera a criação de uma conta nova de emergência.
- Esse admin **não** nasce com troca obrigatória (quem digitou a senha é o próprio titular). A auditoria registra a criação como ação do sistema (`usuario_id` NULL, `operacao = criar_admin_terminal`).
- Duas execuções simultâneas são serializadas por `pg_advisory_xact_lock`.

## Configuração

Variáveis lidas do ambiente **do processo da API**. Assim como `RFID_RECENCY_THRESHOLD_MINUTES`, precisam estar exportadas ao iniciar o uvicorn. Estão documentadas em `.env.example`, `.env.local.example` e `.env.cloud.example`.

| Variável | Padrão | Validação |
|---|---|---|
| `SESSAO_DURACAO_MINUTOS` | 480 | inteiro > 0 |
| `LOGIN_MAX_TENTATIVAS` | 5 | inteiro > 0 |
| `LOGIN_BLOQUEIO_MINUTOS` | 15 | inteiro > 0 |
| `SESSAO_COOKIE_SEGURO` | `true` | `true` ou `false` (sem diferenciar maiúsculas) |
| `LOG_LEVEL` | `INFO` | nível do logger `api` |

Variável ausente usa o padrão. Valor presente e inválido é **erro**: a subida do app falha no `lifespan` e não cai em padrão silencioso. O relógio (`obter_agora`) e a configuração (`obter_configuracao_auth`) são dependencies do FastAPI, e os testes as substituem para avançar o tempo sem `sleep`.

`SESSAO_COOKIE_SEGURO=false` serve só para clientes HTTP puros como o `curl` do smoke; navegadores já aceitam cookie `Secure` em `http://localhost`.

## Schema (migration `d026a1b2c3d4`, filha de `c032b1a2d3e4`)

- Semeia os perfis `operacional` e `administrador` (`ON CONFLICT DO NOTHING`).
- Normaliza `usuarios.email` e cria a CHECK `ck_usuarios_email_normalizado`. **Antes de alterar qualquer coisa**, trava a tabela e procura e-mails que colidiriam após a normalização. Se houver, aborta listando **apenas os ids** por grupo (e-mail é dado pessoal e não vai para log de deploy). Nada é alterado.
- Novas colunas em `usuarios`: `deve_trocar_senha` (false), `tentativas_falhas` (0, CHECK ≥ 0), `bloqueado_ate`, `ultimo_login_em` e `updated_at`.
- Nova tabela `sessoes`: `token_hash` UNIQUE, com CHECK de hex de 64 caracteres (impede gravar token em claro por engano); CHECK `expira_em > criada_em`; `revogada_em` e `motivo_revogacao` preenchidos juntos; motivo em (`logout`, `troca_senha`, `redefinicao_senha`, `desativacao`); índice parcial por `usuario_id` nas não revogadas.
- **Downgrade**: remove `sessoes`, as colunas e as CHECKs. Apaga um perfil semeado só se nenhum usuário o referenciar. Os e-mails continuam normalizados, porque a forma original não foi guardada.

Detalhes em [data-model.md](../architecture/data-model.md) e no [diagrama ER](../architecture/er-diagrama.mermaid).

## Concorrência

- **Login e troca de senha** travam a linha do titular (`SELECT ... FOR UPDATE`) durante a verificação, para falhas simultâneas serem todas contadas e o bloqueio disparar exatamente uma vez.
- **Administração**: toda mudança de usuário trava **primeiro** o conjunto de administradores ativos, em ordem de id, e **só depois** a linha do alvo (`api/service_usuarios.py::_travar`). Travar o alvo antes causava deadlock real quando dois admins se rebaixavam ao mesmo tempo. Com a ordem fixa, a segunda transação espera a primeira, relê o conjunto já atualizado e é recusada: 409 se o alvo virou o último admin, 403 se o próprio autor perdeu o perfil. O sistema nunca fica com zero administradores.
- Login e troca de senha travam uma única linha e nunca esperam por outra, então não formam ciclo com esse protocolo.
- Os hashes Argon2 (caros) são calculados **antes** de pegar os locks.

## Logs

O uvicorn só configura os próprios loggers. Sem configuração, todo INFO de `api.*` era descartado no servidor real, embora o `caplog` dos testes capturasse de qualquer jeito. `api/logging_config.py` adiciona **um** handler (idempotente) ao logger `api`, com nível por `LOG_LEVEL` e `propagate` ligado. `api/main.py` o chama no import.

Eventos em uma linha JSON (`api.auth`): `login_aceito`, `login_recusado` (com `motivo` interno: `senha_incorreta`, `hash_invalido`, `conta_inexistente`, `conta_inativa`, `conta_bloqueada`), `conta_bloqueada`, `logout`, `senha_trocada` e `troca_senha_recusada`. Nunca registram senha, hash ou token. Na tentativa com conta inexistente, o e-mail digitado **não** é registrado (é comum digitarem a senha nesse campo). Quando a conta existe, o evento identifica por `usuario_id`.

Criação e edição de usuário gravam em `auditorias` na mesma transação: `acao` `create`/`update`, autor, `dados_antes`/`dados_depois` sem segredo e `operacao` (`criar`, `editar`, `desativar`, `reativar`, `redefinir_senha`).

## Arquivos

- Novos: `api/config_auth.py`, `api/senhas.py`, `api/logging_config.py`, `api/service_auth.py`, `api/service_usuarios.py`, `api/dependencias_auth.py`, `api/schemas_auth.py`, `api/router_auth.py`, `api/router_usuarios.py`, `api/criar_admin.py` e a migration `alembic/versions/d026a1b2c3d4_iss026_usuarios_autenticacao.py`.
- Alterados: `api/main.py` (routers, logging, validação na subida, handler de 422), `db/models.py`, `requirements.txt` (`argon2-cffi`), os três `.env.*.example`, `tests/conftest.py` (limpa `sessoes` e `usuarios`, **não** `perfis`), `tests/test_migrations.py` e `.github/workflows/migrations.yml` (19 tabelas e a nova head).
- Testes: `tests/suporte_auth.py`, `test_auth_api.py`, `test_usuarios_api.py`, `test_auth_concorrencia.py`, `test_migration_iss026.py`, `test_criar_admin.py` e `test_auth_config.py`.

## Validação e evidências

```bash
python -m ruff check --select E4,E7,E9,F,I .
python -m pytest -q                      # exige TEST_DATABASE_URL local
python -m alembic upgrade head && python -m alembic check
```

- Todos os testes usam Postgres real, sem sqlite nem mock. O `TestClient` usa `base_url="https://testserver"`, porque o cookie é `Secure`.
- **Concorrência**: 8 falhas simultâneas (threads com barreira) contra limite 5 dão exatamente um bloqueio e contador zerado. No rebaixamento cruzado simultâneo, uma barreira **dentro** do lock dos admins força a intercalação: exatamente um é recusado, sem deadlock, e resta 1 admin. Com a ordem invertida, essa mesma barreira reproduz o deadlock de forma determinística. Os testes rodam 5 vezes cada, e a suíte de concorrência foi executada repetidamente em sequência.
- **Migration** em banco descartável próprio: dados legados (e-mail com maiúscula e espaço, perfil `operacional` ausente, hash bcrypt), colisão abortando sem alterar nada, ciclo upgrade → downgrade → upgrade e `alembic check` sem diferença.
- **Teste por mutação**: 76 regras de segurança foram quebradas de propósito, uma por vez, e 75 derrubaram algum teste. A que sobreviveu revelou um caso não coberto: um hash Argon2id com parâmetros legíveis mas sal ou corpo corrompido passa pelo filtro de formato e faz o `verify` levantar exceção. O código já recusava; agora esse caso também executa a verificação fictícia completa e tem teste próprio. As 3 mutações refeitas nesse trecho morreram.
- **Smoke com uvicorn real** (curl com cookie jar): o fluxo completo de login, senha temporária, troca, bloqueio, desativação, reativação, redefinição, logout e 409/422 se comportou como o contrato. Os seis eventos apareceram no log do servidor. Uma varredura do log e de um `pg_dump` não encontrou nenhuma das senhas nem dos tokens usados; no banco só estão os SHA-256 dos tokens.

## Limites e pendências

- Bloqueio por **conta**, não por IP: um atacante pode bloquear uma conta de propósito. Limitar a taxa por IP depende de proxy reverso (ver ADR 0009).
- CSRF coberto por `SameSite=Strict` **enquanto front e API tiverem a mesma origem**.
- As rotas existentes seguiram públicas até a [ISS-027](iss-027-perfis-rbac.md), que passou a exigir sessão e permissão nelas.
- Sessões revogadas ou expiradas não são expurgadas (retenção, RNF-015).
- `updated_at` de `usuarios` segue a ressalva de `equipamentos`: `onupdate` só dispara em UPDATE feito pelo SQLAlchemy.

## Complemento de interface

A administração de contas está disponível em `#/usuarios`, conforme o [frontend de usuários e auditoria](iss-026-028-frontend-administracao.md). Login e troca obrigatória de senha permanecem na ISS-027.
