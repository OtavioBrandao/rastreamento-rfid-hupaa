# Limpeza segura do banco de dados

`python -m tools.limpeza_banco` remove dados experimentais acumulados nos
ensaios e deixa o banco pronto para novas demonstrações, **preservando
usuários, perfis, sessões de login, auditoria e migrations**. Nunca apaga
tabelas. Execute somente em banco local ou de demonstração, depois de um
backup. Não rode em bancos compartilhados (Neon da equipe) sem combinar.

## Classificação dos dados

| Dado | Tabela(s) | Tratamento |
|---|---|---|
| Usuários, perfis, senhas (Argon2id) | `usuarios`, `perfis` | **Preservado** (conferido antes/depois; diferença aborta) |
| Sessões de login | `sessoes` | Preservado (registros de segurança) |
| Trilha de auditoria | `auditorias` | **Preservada**; append-only por trigger; a limpeza só **acrescenta** um registro |
| Migrations | `alembic_version` | Preservada |
| Leituras brutas | `leituras_brutas` | Removidas (escopo `telemetria`) |
| Passagens e direção | `passagens` | Removidas (`telemetria`) |
| Histórico de movimentações | `historico_movimentacoes` | Removido (`telemetria`), inclusive correções manuais de teste |
| Última zona dos equipamentos | colunas `ultima_*` de `equipamentos` | Zeradas, equipamento mantido (`telemetria`) |
| Último contato dos leitores | colunas de contato em `leitores` | Zeradas → "nunca conectado" (`telemetria`) |
| Sessões do simulador web | `simulacao_sessoes` | Removidas (`simulacao`) |
| Leitores virtuais `SIM-*`, suas antenas e mapeamentos | `leitores`, `antenas`, `mapeamentos_antena_portal` | Removidos (`simulacao`) |
| Andar "Simulação HUPAA" (setores, zonas, portais sem antena física) | hierarquia e `portais` | Removidos (`simulacao`) |
| Layouts do simulador | `simulacao_layouts` | **Mantidos** (configuração); vínculos zerados; `--incluir-layouts` remove |
| Equipamentos do launcher (`LAB-RFID-*` ou tipos de laboratório) | `equipamentos`, `associacoes_tag_equipamento` | Removidos (`laboratorio`) |
| Tags sem nenhum vínculo | `tags` | Removidas (`laboratorio`) |
| Equipamentos cadastrados pelo dashboard | `equipamentos` | **Mantidos**; só saem com `--incluir-equipamento ID` |
| Tipos de equipamento | `tipos_equipamento` | Mantidos (exceto os de laboratório sem uso) |
| Zonas, portais e leitores físicos; cadastro do laboratório EASY | hierarquia, hardware | **Mantidos** (configuração de referência) |

Situação registrada: não há como distinguir com segurança um equipamento real
de um cadastrado em demonstração pelo dashboard (ambos usam o mesmo fluxo).
Por isso a ferramenta não os remove automaticamente; inative-os pela
interface (baixa lógica) ou informe os ids explicitamente.

## Comandos

Ubuntu 24.04, na raiz do repositório, com o ambiente local (`.env.local`):

### 1. Visualizar o que será removido

```bash
python -m tools.limpeza_banco previa --env-file config/environments/.env.local
```

Mostra `APP_ENV`, o banco de destino (sem senha), a migration atual, a
contagem por etapa e os totais preservados. Roda em transação **somente
leitura**: não altera nada. Restrinja com `--escopo telemetria` (repetível).

### 2. Criar um backup

Banco local do Compose:

```bash
mkdir -p data/backups
docker compose -f deploy/compose.yaml --profile local -p rfid-hospital-local exec -T postgres \
  pg_dump -U rfid_dev -d rfid_hospital_dev -Fc > data/backups/antes-limpeza.dump
```

Banco externo: use o backup/PITR do provedor ou `pg_dump -Fc "$DATABASE_URL"`
com o endpoint direto. `data/` é ignorado pelo Git.

### 3. Executar a limpeza autorizada

```bash
python -m tools.limpeza_banco executar --env-file config/environments/.env.local \
  --confirmar rfid_hospital_dev
```

`--confirmar` precisa ser o nome exato do banco. Travas:

- `APP_ENV=production` → recusa sempre.
- Host fora de `localhost`/`postgres` → recusa, salvo `--permitir-banco-remoto`
  (use apenas num banco descartável de demonstração).
- Tudo em **uma** transação com `lock_timeout`; qualquer falha desfaz tudo.
- Se usuários, perfis ou auditoria mudassem, a transação é abortada.

### 4. Conferir a integridade

```bash
python -m tools.limpeza_banco verificar --env-file config/environments/.env.local
```

Confere perfis, administrador ativo, hashes Argon2id, trigger append-only da
auditoria, vínculos ativos únicos por tag, projeções sem referência órfã e
FKs validadas. Código de saída 1 se alguma checagem falhar.

### 5. Verificar que os usuários continuam autenticando

Entre no dashboard com uma conta existente ou:

```bash
curl -i -X POST http://127.0.0.1:8010/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@hupaa.example","senha":"<digite a senha>"}'
```

Resposta `200` com `Set-Cookie: rfid_sessao=...` confirma o acesso.

## Restauração

```bash
docker compose -f deploy/compose.yaml --profile local -p rfid-hospital-local exec -T postgres \
  pg_restore -U rfid_dev -d rfid_hospital_dev --clean --if-exists < data/backups/antes-limpeza.dump
```

Depois, `python -m tools.limpeza_banco verificar`. Em banco gerenciado,
prefira restaurar para um *branch*/instância nova e trocar a URL.

## Validação realizada

- Testes automatizados (`tests/test_limpeza_banco.py`) em schema PostgreSQL
  descartável: prévia sem efeito e somente leitura; remoção do experimental;
  usuários, perfis e auditoria preservados; auditoria continua imutável;
  equipamento cadastrado só sai com id explícito; execução repetível; travas
  de produção, banco remoto e confirmação.
- Execução manual em 23/10/2026 no PostgreSQL local isolado do Docker
  (`rfid_hospital_dev`): backup `pg_dump -Fc`, prévia, recusa sem
  `--confirmar`, execução, `verificar` com 8/8 OK e login HTTP 200 após a limpeza.
- **Nenhuma** exclusão foi executada no Neon ou em banco compartilhado.
