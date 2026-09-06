# Modelagem de Dados — MVP Rastreamento RFID (EASY/HUPAA)

Documento de apoio à issue de modelagem (Épico E1, Must, RF-001 a RF-023, RNF-006/011/015). Complementa o diagrama `ER_Diagrama_MVP_RFID.mermaid` (mesma pasta) — abra em [mermaid.live](https://mermaid.live) para editar visualmente ou exportar como imagem, mas o `.mermaid` já é o artefato versionável (texto puro, diffável no Git).

## 1. Convenções adotadas

- **Nomenclatura:** tabelas em português, plural, `snake_case` (ex.: `equipamentos`, `leituras_brutas`).
- **Timestamps:** todas as colunas de tempo são `TIMESTAMPTZ`. A aplicação sempre grava em UTC; o Postgres já armazena internamente em UTC independente da timezone da sessão — a disciplina de sempre enviar UTC é da camada de ingestão, não do banco.
- **Estratégia de ID:** `BIGINT GENERATED ALWAYS AS IDENTITY` como PK interna em todas as tabelas (simples, sequencial, suficiente para o volume do MVP). Exceção: `leituras_brutas.event_id` é `UUID`, porque é gerado na borda (ingestão MQTT, potencialmente por múltiplos leitores concorrentes) e precisa ser único sem depender de uma sequência central — é a chave de idempotência pedida pelo RF-008.

## 2. Entidades e colunas

### `tipos_equipamento`
| Coluna | Tipo | Regra |
|---|---|---|
| id | bigint | PK |
| nome | varchar | UNIQUE, NOT NULL |
| descricao | text | NULL |

### `equipamentos`
| Coluna | Tipo | Regra |
|---|---|---|
| id | bigint | PK |
| nome | varchar | NOT NULL |
| tipo_id | bigint | FK → tipos_equipamento, NOT NULL |
| identificador_interno | varchar | UNIQUE, NOT NULL (nº de patrimônio) |
| status | varchar | NOT NULL, default `ativo` |
| ultima_zona_id | bigint | FK → zonas, NULL |
| ultima_deteccao_em | timestamptz | NULL |
| ultima_passagem_id | bigint | FK → passagens, NULL |
| created_at / updated_at | timestamptz | NOT NULL, default now() |

> RF-012 (última zona conhecida) foi resolvido como **colunas diretas no próprio equipamento**, não uma tabela separada — é uma relação 1:1, e criar uma tabela `localizacoes_atuais` só adicionaria um join sem ganho real.

**Índices:** `ultima_zona_id` (busca por localização, RF-014/015), `status`.

### `tags`
| Coluna | Tipo | Regra |
|---|---|---|
| id | bigint | PK |
| epc | varchar | UNIQUE, NOT NULL |
| criada_em | timestamptz | NOT NULL, default now() |

### `associacoes_tag_equipamento`
Histórico de vínculo entre tag e equipamento (suporta troca de tag sem perder rastreabilidade — RF-003).

| Coluna | Tipo | Regra |
|---|---|---|
| id | bigint | PK |
| tag_id | bigint | FK → tags, NOT NULL |
| equipamento_id | bigint | FK → equipamentos, NOT NULL |
| inicio | timestamptz | NOT NULL, default now() |
| fim | timestamptz | NULL (**NULL = associação ativa**) |

**Constraints críticas (critério de aceitação — "no máximo uma associação ativa por EPC"):**
```sql
CREATE UNIQUE INDEX uq_tag_ativa ON associacoes_tag_equipamento (tag_id) WHERE fim IS NULL;
CREATE UNIQUE INDEX uq_equipamento_tag_ativa ON associacoes_tag_equipamento (equipamento_id) WHERE fim IS NULL;
```
Índices parciais garantem a regra a nível de banco, não só de aplicação.

### `andares`, `setores`, `zonas`
Hierarquia física simples: andar → setor → zona. `zonas.observacoes` é o lugar para documentar textualmente a presença de zona morta dentro daquela zona — **zona morta não é uma entidade própria**, é uma característica descritiva de uma zona já existente (conforme os "Termos e definições" do doc de arquitetura).

`UNIQUE(andar_id, nome)` em setores e `UNIQUE(setor_id, nome)` em zonas evitam duplicidade de nomenclatura dentro do mesmo pai.

### `portais`
| Coluna | Tipo | Regra |
|---|---|---|
| id | bigint | PK |
| nome | varchar | NOT NULL |
| zona_a_id | bigint | FK → zonas, NOT NULL |
| zona_b_id | bigint | FK → zonas, NOT NULL |
| localizacao_fisica | text | NULL |

`CHECK (zona_a_id <> zona_b_id)` — um portal sempre liga duas zonas distintas (é o conceito de "conjunto de antenas posicionadas para detectar entrada/saída de uma zona").

### `leitores`
| Coluna | Tipo | Regra |
|---|---|---|
| id | bigint | PK |
| portal_id | bigint | FK → portais, NULL (leitor pode ser cadastrado antes de instalado) |
| fabricante | varchar | NOT NULL |
| modelo | varchar | NOT NULL |
| identificador_serial | varchar | UNIQUE, NOT NULL |
| endereco_rede | varchar | NULL (IP/hotspot, ex.: DR-pad) |
| status | varchar | NOT NULL, default `offline` |
| ultimo_heartbeat_em | timestamptz | NULL |

`fabricante`/`modelo` como colunas livres (não enum fechado) é o que garante suporte a múltiplos fabricantes/modelos sem alterar schema — critério de aceitação explícito.

### `antenas`
| Coluna | Tipo | Regra |
|---|---|---|
| id | bigint | PK |
| leitor_id | bigint | FK → leitores, NOT NULL |
| porta_numero | int | NOT NULL |
| zona_associada_id | bigint | FK → zonas, NOT NULL |
| funcao | varchar | NOT NULL, CHECK IN ('entrada','saida','indefinido') |

`UNIQUE(leitor_id, porta_numero)` — cada porta física do leitor só pode estar ligada a uma antena por vez.

### `leituras_brutas` (RF-007, RF-008)
| Coluna | Tipo | Regra |
|---|---|---|
| id | bigint | PK |
| event_id | uuid | UNIQUE, NOT NULL — chave de idempotência |
| antena_id | bigint | FK → antenas, NOT NULL |
| epc | varchar | NOT NULL — **sem FK direta para `tags`**: uma leitura pode chegar de um EPC ainda não cadastrado, e a leitura bruta não pode ser perdida por causa disso |
| rssi | numeric | NOT NULL (já corrigido pela regra "/100 quando abs>100" na camada de ingestão, antes de persistir) |
| lido_em | timestamptz | NOT NULL — timestamp do leitor |
| recebido_em | timestamptz | NOT NULL, default now() — quando chegou no backend |

**Índices:** `(epc, lido_em)` e `(antena_id, lido_em)` — são as duas consultas mais frequentes (janela temporal por tag, janela temporal por antena para inferência de passagem).

> Nota para RNF-015 (retenção/volume): esta é a tabela que mais cresce. Fica registrado como decisão futura (não bloqueante pro MVP) considerar particionamento por mês, algo natural de fazer depois via `TimescaleDB` no próprio Postgres, sem trocar de banco.

### `passagens` (RF-009 a RF-011)
| Coluna | Tipo | Regra |
|---|---|---|
| id | bigint | PK |
| epc | varchar | NOT NULL |
| portal_id | bigint | FK → portais, NOT NULL |
| antena_origem_id | bigint | FK → antenas, NOT NULL |
| antena_destino_id | bigint | FK → antenas, NULL — **NULL enquanto a inferência de direção (RF-011, Should) não estiver implementada** |
| direcao | varchar | NULL, CHECK IN ('entrada','saida','indeterminada') |
| leitura_origem_id | bigint | FK → leituras_brutas, NOT NULL |
| leitura_destino_id | bigint | FK → leituras_brutas, NULL |
| detectada_em | timestamptz | NOT NULL |

**Índices:** `(epc, detectada_em)`, `(portal_id, detectada_em)`.

### `historico_movimentacoes` (RF-013)
| Coluna | Tipo | Regra |
|---|---|---|
| id | bigint | PK |
| equipamento_id | bigint | FK → equipamentos, NOT NULL |
| zona_origem_id | bigint | FK → zonas, NULL |
| zona_destino_id | bigint | FK → zonas, NOT NULL |
| passagem_id | bigint | FK → passagens, NULL — **NULL indica correção manual (RF-020)** |
| origem_registro | varchar | NOT NULL, CHECK IN ('passagem_automatica','correcao_manual') |
| registrado_em | timestamptz | NOT NULL, default now() |

**Índice:** `(equipamento_id, registrado_em)` — é a consulta direta do histórico de um ativo.

### `perfis` / `usuarios` (RF-021, RF-022)
Simples: `perfis` com `operacional`/`administrador`; `usuarios` referenciando `perfis`, com `email` único e `senha_hash` (nunca senha em texto puro).

### `auditorias` (RF-023, RNF-006)
| Coluna | Tipo | Regra |
|---|---|---|
| id | bigint | PK |
| usuario_id | bigint | FK → usuarios, NULL (NULL = ação automática do sistema) |
| entidade | varchar | NOT NULL — nome da tabela afetada |
| entidade_id | bigint | NOT NULL |
| acao | varchar | NOT NULL, CHECK IN ('create','update','delete','correcao_manual') |
| dados_antes | jsonb | NULL |
| dados_depois | jsonb | NULL |
| registrado_em | timestamptz | NOT NULL, default now() |

Genérica o suficiente pra auditar qualquer tabela sem precisar de uma tabela de auditoria por entidade. **Índice:** `(entidade, entidade_id, registrado_em)`.

---

## 3. Rastreabilidade (critério de aceitação)

`leituras_brutas.antena_id → antenas.leitor_id → leitores` (leitor) e `antenas.zona_associada_id/leitor.portal_id → portais` (portal). Do lado do ativo: `leituras_brutas.epc → tags.epc → associacoes_tag_equipamento (fim IS NULL) → equipamentos`. Uma leitura sempre chega até leitor/antena/portal; até o ativo, apenas quando o EPC tiver associação ativa registrada — leitura de EPC não cadastrado fica órfã do lado do ativo, mas nunca é perdida.

## 4. Cenários de validação cruzada (para revisão da dupla)

1. **Cadastro:** `tipos_equipamento` → `equipamentos` → `tags` → `associacoes_tag_equipamento` (ativa).
2. **Passagem entre duas zonas:** duas `leituras_brutas` (antenas distintas do mesmo portal) dentro da janela de debounce → gera 1 `passagens` (origem + destino se direção inferida) → atualiza `equipamentos.ultima_zona_id/ultima_deteccao_em` → insere 1 linha em `historico_movimentacoes` com `origem_registro='passagem_automatica'`.
3. **Troca de tag:** associação ativa antiga recebe `fim = now()`; nova linha criada para a nova tag no mesmo equipamento — o equipamento mantém histórico completo de EPCs já usados, sem perder o histórico de movimentação anterior (que referencia o equipamento, não a tag).
4. **Correção manual:** admin altera `equipamentos.ultima_zona_id` diretamente → `historico_movimentacoes` recebe linha com `passagem_id = NULL` e `origem_registro='correcao_manual'` → `auditorias` recebe entrada com `dados_antes`/`dados_depois` e `usuario_id` preenchido.

## 5. Decisões e dúvidas pendentes do HUPAA

- **Nomenclatura oficial de andares/setores:** o hospital já tem uma codificação própria (ex.: "4º andar — Ala Norte")? Alinhar `zonas.nome` a essa nomenclatura desde já evita retrabalho depois.
- **Retenção de `leituras_brutas` (RNF-015):** ainda sem patamar formal — decisão do MVP é reter tudo e revisitar quando o volume no Neon free tier se tornar um limitador real.
- **Backup/recuperação (RNF-011):** confirmar qual plano do Neon garante quantos dias de *point-in-time recovery* — hoje ainda não definimos RPO/RTO formal.
- **Residência de dados:** já sinalizado no documento de hospedagem — se o HUPAA exigir dado em território nacional, a região `AWS US East 2 (Ohio)` do Neon precisa ser revista.

## 6. O que isso desbloqueia
Esta modelagem alimenta diretamente **ISS-002c** (migrations) e orienta a implementação de **ISS-008 a ISS-018** (cadastro base + inferência de passagem).
