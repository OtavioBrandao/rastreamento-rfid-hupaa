# Configuração do Neon (PostgreSQL gerenciado) — ISS-002b

Documento de apoio à ISS-002b (Épico E1, Must, RNF-004, RNF-011, RNF-014, RNF-016). Projeto Neon: **HU RFID**, região `AWS US East 2 (Ohio)`.

## 1. Roles — migrations vs. aplicação

O Neon cria automaticamente um role dono do banco (`neondb_owner`) com a permissão especial `neon_superuser` (pode criar roles/databases, DML irrestrito). **Qualquer role criado pelo Console/API/CLI do Neon também vira `neon_superuser` automaticamente** — só roles criados via SQL puro (psql/SQL Editor) recebem os privilégios básicos padrão do Postgres. Por isso os dois roles do projeto foram criados de formas diferentes:

| Role | Uso | Como foi criado | Privilégios |
|---|---|---|---|
| `neondb_owner` | **Migrations** (Alembic) | Automático do Neon | `neon_superuser` — DDL completo (CREATE/ALTER/DROP) |
| `rfid_app` | **Aplicação** (futuro backend, ISS-008+) | Via SQL (`CREATE ROLE`), **não** pelo Console | Só DML: `SELECT`/`INSERT`/`UPDATE`/`DELETE`; sem `CREATE` no schema |

Confirmado por consulta direta que `rfid_app` não é superuser nem pode criar role/database/tabela:
```sql
SELECT rolname, rolsuper, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = 'rfid_app';
--  rolname  | rolsuper | rolcreaterole | rolcreatedb
-- ----------+----------+---------------+-------------
--  rfid_app | f        | f             | f
```

> **Limitação conhecida:** hoje as credenciais (`neondb_owner` e `rfid_app`) são compartilhadas entre os dois integrantes da dupla — não existe uma senha por pessoa. Funciona para o escopo atual (MVP acadêmico, dupla pequena), mas impede auditoria de acesso por indivíduo. Revisitar se o projeto crescer além da dupla ou se o HUPAA exigir rastreabilidade de acesso por usuário.

### SQL de criação (já executado, registrado para reprodutibilidade)
```sql
CREATE ROLE rfid_app WITH LOGIN PASSWORD '<gerada com openssl rand -base64 24>';

GRANT CONNECT ON DATABASE neondb TO rfid_app;
GRANT USAGE ON SCHEMA public TO rfid_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO rfid_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO rfid_app;

-- Tabelas/sequences futuras (criadas por migrations rodadas como neondb_owner)
-- já herdam esses privilégios automaticamente, sem precisar repetir o GRANT:
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rfid_app;
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO rfid_app;

REVOKE CREATE ON SCHEMA public FROM rfid_app;
```

## 2. SSL — obrigatório, sem opção de desligar

O Neon rejeita qualquer conexão sem SSL/TLS no nível do servidor (não é configurável, nem no free tier). Além disso, todas as connection strings do projeto usam `channel_binding=require` — que resolve a fraqueza conhecida de `sslmode=require` sozinho (vulnerável a man-in-the-middle, pois não verifica a identidade do servidor). Com `channel_binding=require`, a autenticação SCRAM fica vinculada ao canal TLS, dando proteção equivalente a `verify-full` sem precisar configurar certificado raiz manualmente.

Testado: `psql` reportou `SSL connection (protocol: TLSv1.3, cipher: TLS_AES_256_GCM_SHA384)`.

## 3. Pooled vs. Direct — quando usar cada uma

O Neon expõe duas connection strings pro mesmo banco, diferindo só por `-pooler` no host:

| | Direct (sem `-pooler`) | Pooled (com `-pooler`) |
|---|---|---|
| **Usar para** | Migrations, scripts admin | Tráfego de aplicação (futuro backend) |
| **Motivo** | PgBouncer (modo transaction) devolve a conexão ao pool a cada transação, quebrando recursos de sessão que ferramentas de migration podem precisar | Suporta até 10.000 conexões concorrentes — essencial pra apps com muitas requisições curtas |
| **Recomendação oficial do Neon** | "usar conexão direta ao rodar migrations" (guia deles de SQLAlchemy+Alembic) | Padrão pra apps serverless/alta concorrência |

**Decisão do projeto:** `DATABASE_URL` (usada pelo `alembic/env.py`) = **direct**. `APP_DATABASE_URL` (reservada pro backend, ainda não usada por nenhum código) = **pooled**.

## 4. Variáveis de ambiente

Adicionadas em `.env.example`, `.env.local.example` e `.env.cloud.example` (placeholders, sem segredo real):

DATABASE_URL=postgresql+psycopg2://neondb_owner:<senha>@<host>.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require
APP_DATABASE_URL=postgresql+psycopg2://rfid_app:<senha>@<host>-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require


> Nota: o Neon fornece a string com prefixo `postgresql://`; o SQLAlchemy/Alembic exige `postgresql+psycopg2://` (driver explícito) — ajustar manualmente ao colar no `.env`.

`.env` real nunca é commitado (já coberto pelo `.gitignore` existente do projeto).

## 5. Limites do plano Free (verificado, pode mudar — revisar periodicamente)

| Limite | Valor |
|---|---|
| Compute | 100 CU-horas/mês por projeto (≈400h de um compute de 0,25 CU) |
| Armazenamento | 0,5 GB por projeto |
| Tráfego de rede público | 5 GB/mês por projeto |
| Branches | 10 por projeto |
| Scale to zero | Suspende após **5 minutos de inatividade** — não pode ser desligado no Free. Primeira query após suspensão tem alguns segundos de latência extra (cold start) |
| Backup / PITR | **6 horas** de histórico de restauração instantânea (limitado a 1 GB-mês de mudanças) + 1 snapshot manual |
| Histórico de monitoramento | 1 dia |

**Impacto prático já observado:** durante a configuração, uma sessão `psql` ficou parada poucos minutos (enquanto configurávamos o `.env` em outro terminal) e o compute suspendeu no meio de uma sequência de comandos SQL — o `psql` reconectou sozinho, mas os comandos que ainda não tinham rodado falharam (`role "rfid_app" does not exist`, porque o `CREATE ROLE` anterior nunca chegou a executar antes da queda). **Lição prática:** ao rodar uma sequência de comandos SQL relacionados, evitar pausas longas no meio — ou aceitar que pode ser necessário rodar o bloco de novo do início.

**RNF-011 (backup):** as 6h de PITR do Free tier são uma janela curta pra um "backup" no sentido forte — registrado como limitação conhecida, a ser revisitada se o projeto migrar pra um plano pago ou se RPO/RTO formais forem exigidos pelo HUPAA.

## 6. Branch do Neon para testar migrations sem afetar o banco principal

```bash
# via Neon CLI (npm install -g neonctl)
neonctl branches create --name teste-migration --parent main
```

Cria uma cópia copy-on-write do banco (schema + dados) com sua própria connection string e compute. Fluxo recomendado: aplicar uma migration nova primeiro nessa branch de teste; só rodar contra o banco principal (`main`) depois de validar. Branches de teste devem ser apagadas depois de usadas (contam pro limite de 10 branches/projeto).

## 7. Recuperação e rotação de credenciais

**Recuperação:** usar "Instant restore" no painel do Neon — escolher um ponto no tempo dentro da janela de 6h e o Neon recria uma branch naquele estado.

**Rotação de senha** (procedimento):
```sql
ALTER ROLE rfid_app WITH PASSWORD '<nova senha>';
```
Depois: atualizar `.env` em todos os ambientes que usam esse role, e reiniciar qualquer processo que já tivesse a senha antiga carregada em memória. A senha antiga para de funcionar imediatamente após o `ALTER ROLE` — coordenar com a dupla antes de rotacionar em produção pra evitar interrupção.

## 8. Incidente registrado durante a configuração (lição aprendida)

Ao rodar `alembic upgrade head` pela primeira vez contra o Neon, a migration aplicada foi a **versão antiga** (`f2d8d6cd6b62`, anterior às correções da revisão de código do Otávio — sem o `CHECK` de período válido, sem a correção do `event_id`). Causa raiz: o ambiente local (notebook) estava numa branch Git desatualizada (`feat/iss-002a-modelagem-dados`, no primeiro commit), porque o `git pull` da `main` mergeada nunca tinha sido feito nesse ambiente específico.

**Correção aplicada:**
1. `alembic downgrade base` — revertido enquanto o arquivo de migration antigo ainda existia localmente (importante: reverter *antes* de atualizar o código, senão o Alembic perde a referência de como desfazer a migration errada)
2. `git checkout main && git pull origin main` — trouxe a migration corrigida (`44ef89b10f17`)
3. `alembic upgrade head` — reaplicado com o schema correto, confirmado via `\d associacoes_tag_equipamento` que o `ck_associacao_periodo_valido` estava presente

**Prática recomendada daqui pra frente:** antes de rodar qualquer migration contra o Neon de produção, confirmar `git log --oneline -5` e `ls alembic/versions/` — checar que o ambiente está atualizado com a `main`, especialmente em ambientes/notebooks usados com menos frequência.

## 9. Validação cruzada (critério de aceitação da issue)

```sql
-- Ambiente 1: insere
INSERT INTO tipos_equipamento (nome, descricao)
  VALUES ('TESTE_ISS002B', 'registro de teste de conexão, remover depois');

-- Ambiente 2: lê
SELECT * FROM tipos_equipamento WHERE nome = 'TESTE_ISS002B';

-- Um dos dois remove ao final
DELETE FROM tipos_equipamento WHERE nome = 'TESTE_ISS002B';
```

## 10. Checklist de critérios de aceitação

- [x] Conexão SSL confirmada (TLS 1.3, `channel_binding=require`)
- [x] Role de aplicação (`rfid_app`) sem privilégio administrativo, criado via SQL
- [x] Segredos fora do repositório (`.env` gitignored, só placeholders nos `.example`)
- [x] Limites do free tier documentados (seção 5)
- [x] Estratégia de branch para testar migrations documentada (seção 6)
- [ ] Conexão validada a partir do ambiente do Otávio — **pendente**
- [ ] Validação cruzada (insert em um ambiente, leitura no outro) — **pendente**, aguardando Otávio
