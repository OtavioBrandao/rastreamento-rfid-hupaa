# 0003 — Modelagem de dados e camada de persistência (PostgreSQL/Neon + SQLAlchemy/Alembic)

## Status
Proposto (aguardando revisão da dupla e merge do PR da ISS-002a)

## Contexto
O MVP precisa persistir ativos, tags, topologia física (andares/setores/zonas/portais/leitores/antenas), leituras brutas, passagens inferidas, histórico de movimentação, usuários e auditoria (RF-001 a RF-023; RNF-006, RNF-011, RNF-015). Até esta decisão, o repositório só tinha a camada de ingestão MQTT (`rfid_ingestion/`), sem nenhuma camada de persistência relacional.

Decisão de banco (PostgreSQL) e de hospedagem (Neon, gerenciado) já haviam sido tomadas anteriormente, fora deste ADR — este documento cobre a modelagem em si e a ferramenta de migrations.

## Decisão
- **ORM/toolchain:** SQLAlchemy (models declarativos) + Alembic (migrations versionadas), ambos commitados no Git.
- **Convenção de nomenclatura:** tabelas em português, plural, `snake_case` (ex.: `equipamentos`, `leituras_brutas`).
- **Estratégia de ID:** `BIGSERIAL` (autoincremento padrão do SQLAlchemy) como PK interna, exceto `leituras_brutas.event_id`, que é `UUID` sem default automático — deve ser gerado de forma determinística pela camada de ingestão.
- **Timestamps:** sempre `TIMESTAMP(timezone=True)`; a aplicação grava em UTC.
- **Última localização conhecida do ativo (RF-012):** modelada como colunas diretas em `equipamentos` (`ultima_zona_id`, `ultima_deteccao_em`, `ultima_passagem_id`), não como tabela separada — é uma relação 1:1, e uma tabela à parte só adicionaria um join sem ganho.
- **Zona morta:** não é uma entidade — é um campo textual (`zonas.observacoes`) descrevendo uma característica de uma zona já existente, conforme o glossário do documento de arquitetura original.
- **Histórico de vínculo tag↔equipamento:** tabela própria (`associacoes_tag_equipamento`) com `inicio`/`fim` (NULL = ativa), garantindo suporte a troca de tag sem perder rastreabilidade (RF-003).
- **Regra "no máximo uma associação ativa por EPC":** garantida via índice único parcial no Postgres (`WHERE fim IS NULL`), não apenas validação de aplicação — constraint a nível de banco.
- **Auditoria (RF-023/RNF-006):** tabela genérica (`auditorias`) com `entidade`/`entidade_id`/`acao`/`dados_antes`/`dados_depois` (JSONB), em vez de uma tabela de auditoria por entidade.

O modelo completo (colunas, constraints, índices, cenários de validação) está documentado em `docs/database/modelagem-dados.md`, com diagrama ER em `docs/database/er-diagrama.mermaid`.

## Validação realizada
Antes deste PR, o schema foi criado e testado contra um PostgreSQL 16 real (ambiente local descartável, não o Neon de produção):
- `alembic upgrade head` cria as 16 tabelas + constraints sem erro.
- `alembic downgrade base` reverte de forma limpa.
- Regra de associação ativa única por EPC testada manualmente: bloqueia segunda associação ativa; permite nova associação após encerrar a anterior (`fim = now()`).
- CHECK constraint de portal (`zona_a_id <> zona_b_id`) testado manualmente: bloqueia portal com a mesma zona nos dois lados.

## Revisão de código (Otávio) — alterações aplicadas
- Correção da idempotência do `event_id`: removido o default `uuid.uuid4` gerado no model; a responsabilidade de gerar um `event_id` determinístico a partir do conteúdo da leitura foi movida para a camada de ingestão (ISS-006).
- Adicionado `CHECK (fim >= inicio)` em `associacoes_tag_equipamento`, com documentação da consulta temporal correta (`inicio <= :t AND (fim IS NULL OR fim > :t)`) e decisão consciente de não impedir sobreposição de períodos via banco no MVP.
- Alinhamento da documentação quanto a `BIGSERIAL` vs. `IDENTITY` como estratégia de PK.
- Validação de coerência de topologia antena/portal (`zona_associada_id` pertencer ao portal do leitor) adiada para a ISS-013.
- Limitação aceita do `updated_at` via ORM: não é atualizado por UPDATEs feitos fora do SQLAlchemy; solução futura seria trigger de banco, não implementada agora.
- Correção das referências de arquivo no cabeçalho de `db/models.py` (caminhos corretos em `docs/database/`).
- Strings livres em `status`/`funcao`/`perfis` mantidas — Otávio concordou que é aceitável por ora.

## Segunda rodada de revisão (Otávio) — alterações aplicadas

Validação do Otávio nesta rodada: suíte do PR com 25 testes aprovados e 4 ignorados (dependências de Mosquitto/OpenSSL); configuração dos 16 models validada via `configure_mappers`; geração offline de upgrade/downgrade bem-sucedida com URL simples; reproduziu `ValueError` com URL sintética contendo `%40`. Migrations não foram executadas contra Postgres real nesta rodada (isso foi feito à parte, neste commit, antes de responder).

1. **[P2] Bug de escaping de `%` em `alembic/env.py`:** `config.set_main_option("sqlalchemy.url", database_url)` passa a URL pelo `ConfigParser` interno do Alembic, que trata `%` como início de interpolação. Uma `DATABASE_URL` com senha percent-encoded (ex.: `%40`) fazia essa chamada lançar `ValueError` **antes mesmo de tentar conectar**, e a mensagem de erro incluía a URL completa — vazando a credencial em log. Corrigido extraindo a resolução da URL para `db/url.py` (`get_database_url`), usada diretamente na criação do Engine/contexto — a URL nunca mais passa pelo `ConfigParser`. Coberto por teste (`tests/test_database_url.py`), incluindo o caso exato do review (`example%40value`); testado também via `alembic upgrade head --sql` com a mesma URL sintética, sem erro.
2. **[P2] Seção "Rastreabilidade" desatualizada:** ainda instruía usar `associacoes_tag_equipamento (fim IS NULL)` para relacionar uma leitura ao ativo — contradizendo o intervalo `[inicio, fim)` já documentado no model/ADR. Corrigido em `docs/database/modelagem-dados.md`: a seção agora distingue explicitamente "vínculo ativo agora" (`fim IS NULL`) de "vínculo no momento da leitura" (`inicio <= lido_em AND (fim IS NULL OR fim > lido_em)`), com o exemplo da troca de tag (cadeira → maca) explicando por que usar só `fim IS NULL` atribuiria uma leitura antiga ao equipamento errado.
3. **Ajustes menores de documentação:** referência ao nome antigo do diagrama (`ER_Diagrama_MVP_RFID.mermaid`) corrigida para o caminho real (`docs/database/er-diagrama.mermaid`); `IDENTITY` trocado por `BIGSERIAL` nos pontos que ainda restavam.
4. **Alinhamento pendente com ISS-005 ([PR #37](https://github.com/OtavioBrandao/rfid-hospital-mvp/pull/37), ainda não integrado):** a proposta da ISS-005 usa `event_id` como texto SHA-256 e `rssi` nullable (valor/unidade em metadata), enquanto este model usa `event_id` UUID e `rssi` obrigatório. **Não resolvido neste PR** — fica registrado como pendência explícita a decidir em conjunto antes da implementação da ISS-006, que é a camada que efetivamente liga os dois contratos. A regra de RSSI (`/100` quando `abs>100`) foi reclassificada na documentação como convenção **não validada fisicamente**, não como requisito fechado.

## Consequências
- Toda mudança de schema a partir de agora passa por `alembic revision --autogenerate` + revisão manual do arquivo gerado — nunca alterar tabela direto no banco.
- Dependências novas em `requirements.txt`: `SQLAlchemy`, `alembic`, `psycopg2-binary`.
- Nova variável de ambiente: `DATABASE_URL` (adicionada aos `.env.*.example`).

## Pendências (dependem do HUPAA — não bloqueiam este PR)
- Nomenclatura oficial de andares/setores do hospital (para alinhar `zonas.nome`).
- Patamar formal de retenção de `leituras_brutas` (RNF-015).
- RPO/RTO formal de backup (RNF-011) — depende de qual plano do Neon for contratado.
- Confirmação de exigência de residência de dados em território nacional (pode impactar a região do Neon, hoje `AWS US East 2 — Ohio`).
