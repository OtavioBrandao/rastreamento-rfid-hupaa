# Modelagem de Dados — MVP Rastreamento RFID (EASY/HUPAA)

Documento de apoio à issue de modelagem (Épico E1, Must, RF-001 a RF-023, RNF-006/011/015). Complementa o diagrama [er-diagrama.mermaid](er-diagrama.mermaid) — abra em [mermaid.live](https://mermaid.live) para editar visualmente ou exportar como imagem, mas o `.mermaid` já é o artefato versionável (texto puro, diffável no Git).

## 1. Convenções adotadas

- **Nomenclatura:** tabelas em português, plural, `snake_case` (ex.: `equipamentos`, `leituras_brutas`).
- **Timestamps:** todas as colunas de tempo são `TIMESTAMPTZ`. A aplicação sempre grava em UTC; o Postgres já armazena internamente em UTC independente da timezone da sessão — a disciplina de sempre enviar UTC é da camada de ingestão, não do banco.
- **Estratégia de ID:** `BIGSERIAL` (autoincremento padrão do SQLAlchemy para `BigInteger, primary_key=True` no dialeto Postgres) como PK interna em todas as tabelas — simples, sequencial, suficiente para o volume do MVP. Exceção: `leituras_brutas.event_id` é `VARCHAR(71)`, sem default; preserva diretamente o ID canônico determinístico `sha256:<64 hex>` da ISS-005.

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

**CHECK de período válido:**
```sql
ALTER TABLE associacoes_tag_equipamento ADD CONSTRAINT ck_associacao_periodo_valido
  CHECK (fim IS NULL OR fim >= inicio);
```

#### Semântica temporal (revisão de código, Otávio)

O intervalo de cada associação é **meio-aberto** `[inicio, fim)` — uma leitura com `lido_em == fim` já pertence à associação **seguinte**, não a essa. Para descobrir a qual equipamento um EPC pertencia no momento T de uma leitura (não necessariamente o vínculo ativo hoje):

```sql
SELECT equipamento_id FROM associacoes_tag_equipamento
WHERE tag_id = :tag_id
  AND inicio <= :t
  AND (fim IS NULL OR fim > :t);
```

É essa consulta que garante o caso citado na revisão: `Tag A → cadeira` em janeiro, `Tag A → maca` em março — uma leitura de janeiro continua apontando pra cadeira, mesmo que hoje a associação ativa seja com a maca.

**O que o banco garante vs. o que fica com a aplicação:** o CHECK acima garante `fim >= inicio` **dentro de uma linha**. Impedir períodos **sobrepostos entre linhas diferentes** da mesma tag (ex.: duas associações "ativas ao mesmo tempo" por bug de aplicação) **não é garantido pelo banco** nesta migration — é responsabilidade da aplicação sempre fechar (`fim = now()`) a associação anterior antes de abrir uma nova, na mesma transação. Se isso se mostrar insuficiente na prática, a evolução natural é uma constraint `EXCLUDE` sobre `tstzrange(inicio, fim)` com a extensão `btree_gist` — deliberadamente não implementada agora, por ser complexidade desnecessária pro volume do MVP.

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
| ativo | boolean | NOT NULL, default `true` (ISS-012 — baixa lógica, nunca DELETE) |
| created_at / updated_at | timestamptz | NOT NULL, default now() (ISS-012) |

Um portal agrega antenas via `antenas.portal_id` (associação direta — **as antenas de um mesmo portal podem vir de leitores diferentes**).

`CHECK (zona_a_id <> zona_b_id)` — um portal sempre liga duas zonas distintas (é o conceito de "conjunto de antenas posicionadas para detectar entrada/saída de uma zona").

### `leitores`
| Coluna | Tipo | Regra |
|---|---|---|
| id | bigint | PK |
| reader_id | varchar | UNIQUE, NOT NULL (ISS-012 — identificador lógico usado como origem no MQTT, segmento `<reader_id>` do tópico; **campo distinto de `identificador_serial`**, os dois podem coincidir por acaso) |
| fabricante | varchar | NOT NULL |
| modelo | varchar | NOT NULL |
| identificador_serial | varchar | UNIQUE, NOT NULL (número de série de fábrica) |
| endereco_rede | varchar | NULL (IP/hotspot, ex.: DR-pad) |
| parametros_ingestao | jsonb | NULL (ISS-012 — metadado de ingestão **estritamente não-secreto**. **Allowlist fechada** de chaves, validada no schema da API: `protocolo`, `adapter`, `formato_timestamp`, `topico`, `qos` — qualquer outra chave é 422, e o valor de cada uma tem forma validada. Senha/credencial de broker fica fora do banco, em env/secret manager) |
| status | varchar | NOT NULL, default `offline` (conectividade ao vivo — gerida pela ingestão/heartbeat) |
| ultimo_heartbeat_em | timestamptz | NULL (idem) |
| ativo | boolean | NOT NULL, default `true` (ISS-012 — cadastro/ciclo de vida, **separado de `status`**) |
| created_at / updated_at | timestamptz | NOT NULL, default now() (ISS-012) |

> **ISS-012:** `leitores.portal_id` foi **removida**. A associação com o portal mora na antena (`antenas.portal_id`): um leitor pode ter antenas em portais diferentes e um portal pode reunir antenas de leitores diferentes.

`fabricante`/`modelo` como colunas livres (não enum fechado) é o que garante suporte a múltiplos fabricantes/modelos sem alterar schema — critério de aceitação explícito.

### `antenas`
| Coluna | Tipo | Regra |
|---|---|---|
| id | bigint | PK |
| leitor_id | bigint | FK → leitores, NOT NULL (imutável: a antena é fisicamente cabeada no leitor) |
| portal_id | bigint | FK → portais, NULL (ISS-012 — associação lógica ao portal; editável, inclusive de volta a NULL) |
| porta_numero | int | NOT NULL |
| zona_associada_id | bigint | FK → zonas, NOT NULL |
| funcao | varchar | NOT NULL, CHECK IN ('entrada','saida','indefinido') |
| ativo | boolean | NOT NULL, default `true` (ISS-012) |
| created_at / updated_at | timestamptz | NOT NULL, default now() (ISS-012) |

`UNIQUE(leitor_id, porta_numero) WHERE ativo` — **índice único parcial** (`uq_antena_ativa_por_porta_leitor`, mesmo padrão de `uq_tag_ativa`): cada porta física do leitor tem no máximo uma antena **ativa**. Inativar uma antena libera a porta para uma antena nova; a linha antiga continua existindo (o histórico de leituras a referencia). Uma porta pode, portanto, ter várias linhas (uma ativa e as demais inativas): quem resolve `(leitor, porta) → antena` — como a ingestão — deve filtrar por `ativo`. Reativar uma antena cuja porta já foi tomada por outra ativa é bloqueado.

> **ISS-013:** A coerência de zonas entre portal e antena foi resolvida com a modelagem da tabela `mapeamentos_antena_portal`, associando antenas aos lados A ou B do portal e às suas zonas correspondentes.

### `mapeamentos_antena_portal` (ISS-013, RF-006)
Topologia lógica temporal versionada que define o significado operacional de uma antena dentro de um portal (lado A ou B, zona adjacente e função operacional).

| Coluna | Tipo | Regra |
|---|---|---|
| id | bigint | PK |
| antena_id | bigint | FK → antenas, NOT NULL |
| portal_id | bigint | FK → portais, NOT NULL |
| lado | varchar | NOT NULL, CHECK IN ('a', 'b') |
| zona_id | bigint | FK → zonas, NOT NULL |
| funcao | varchar | NOT NULL, CHECK IN ('entrada', 'saida', 'auxiliar') |
| inicio | timestamptz | NOT NULL, default now() |
| fim | timestamptz | NULL (**NULL = mapeamento ativo**) |
| created_at | timestamptz | NOT NULL, default now() |

**Constraints e Índices:**
```sql
CREATE UNIQUE INDEX uq_mapeamento_antena_ativo ON mapeamentos_antena_portal (antena_id) WHERE fim IS NULL;
ALTER TABLE mapeamentos_antena_portal ADD CONSTRAINT ck_mapeamento_lado_valido CHECK (lado IN ('a', 'b'));
ALTER TABLE mapeamentos_antena_portal ADD CONSTRAINT ck_mapeamento_funcao_valida CHECK (funcao IN ('entrada', 'saida', 'auxiliar'));
ALTER TABLE mapeamentos_antena_portal ADD CONSTRAINT ck_mapeamento_periodo_valido CHECK (fim IS NULL OR fim >= inicio);
```

- **Semântica temporal `[inicio, fim)`:** Reconfigurações fecham a versão anterior (`fim = now()`) e criam uma nova versão (`inicio = now()`), preservando o histórico para reinterpretação retrospectiva de passagens passadas.
- **Suporte a múltiplas antenas:** Não há unicidade em `(portal_id, lado)`. Múltiplas antenas podem cobrir o mesmo lado do portal simultaneamente.

### `leituras_brutas` (RF-007, RF-008)
| Coluna | Tipo | Regra |
|---|---|---|
| id | bigint | PK |
| event_id | varchar(71) | UNIQUE, NOT NULL — chave de idempotência (ver 2.1 abaixo) |
| antena_id | bigint | FK → antenas, NOT NULL |
| epc | varchar | NOT NULL — **sem FK direta para `tags`**: uma leitura pode chegar de um EPC ainda não cadastrado, e a leitura bruta não pode ser perdida por causa disso |
| rssi | numeric | NULL quando a unidade física não está comprovada |
| dados_origem | jsonb | NULL para compatibilidade; novos eventos guardam metadata canônica, topic, adapter, qos e retain |
| lido_em | timestamptz | NOT NULL — timestamp do leitor |
| recebido_em | timestamptz | NOT NULL, default now() — quando chegou no backend |

**Índices:** `(epc, lido_em)` e `(antena_id, lido_em)` — são as duas consultas mais frequentes (janela temporal por tag, janela temporal por antena para inferência de passagem).

> Nota para RNF-015 (retenção/volume): esta é a tabela que mais cresce. Fica registrado como decisão futura (não bloqueante pro MVP) considerar particionamento por mês, algo natural de fazer depois via `TimescaleDB` no próprio Postgres, sem trocar de banco.

#### 2.1 — Idempotência de mensagem

A PR #37 / ISS-005 já está integrada à main. Seu `event_id` canônico é a fonte
de verdade: `sha256:` e 64 hexadecimais. A persistência usa esse valor diretamente
com `ON CONFLICT (event_id) DO NOTHING RETURNING id`, inclusive sob concorrência.
IDs diferentes permanecem distintos mesmo para o mesmo EPC. Isto não é debounce.

#### 2.2 — Alinhamento com o contrato canônico (ISS-006)

A migration `da436f7c75b3` sucede `6b3e5f7a91c4`, última revisão da ISS-012,
e altera somente o contrato de persistência de `leituras_brutas`: converte
`event_id` de UUID para `VARCHAR(71)`, permite RSSI nulo e adiciona
`dados_origem` JSONB. O `reader_id` pertence à ISS-012 e permanece
`NOT NULL` + `UNIQUE`, independente de `identificador_serial`.

Na ingestão, a antena é resolvida pelo `reader_id` lógico e `porta_numero`,
considerando somente `Antena.ativo = true`; antenas inativas permanecem como
histórico e podem coexistir com uma substituta ativa na mesma porta.
`lido_em` recebe o timestamp canônico e `recebido_em` recebe
`received_at_utc`. RSSI bruto/unidade permanecem na metadata em
`dados_origem`, sem escala física presumida.

O downgrade é reversível no banco vazio do CI. Após gravar IDs `sha256:*`, é
necessário migrar ou remover os dados deliberadamente antes de voltar a UUID;
essa conversão não é semanticamente possível. RSSI nulo também impede restaurar
NOT NULL. A migration falha sem apagar ou inventar dados nessas situações.

#### 2.3 — Observações consolidadas em memória (ISS-014)

A ISS-014 não adiciona tabela: `leituras_brutas` continua sendo a fonte de
verdade. Depois do commit, somente resultados `inserted` alimentam o debounce;
`duplicate` não aumenta a contagem. A chave lógica é `(epc, antena_id)` e usa
`lido_em` como event time. O resultado em memória referencia a primeira e a
última leitura bruta, conserva timestamps e quantidade e agrega mínimo, máximo
e média apenas dos RSSIs não nulos. Consulte a
[documentação da ISS-014](../implementations/iss-014-debounce-leituras.md) para
watermark, finalização automática por silêncio, flush e limitações. O relógio
monotônico usado para perceber silêncio não substitui `lido_em` no agrupamento.

### `passagens` (RF-009 a RF-011)
| Coluna | Tipo | Regra |
|---|---|---|
| id | bigint | PK |
| epc | varchar | NOT NULL |
| portal_id | bigint | FK → portais, NOT NULL |
| antena_origem_id | bigint | FK → antenas, NOT NULL |
| antena_destino_id | bigint | FK → antenas, NULL — preenchimento conforme a detecção de passagem da ISS-015; a direção é escopo da ISS-016 |
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

`leituras_brutas.antena_id → antenas.leitor_id → leitores` (leitor) e `antenas.portal_id → portais` (portal). Uma leitura sempre chega até leitor/antena/portal.

Do lado do ativo, a consulta **depende do que se quer saber**:

- **Vínculo ATIVO agora** (ex.: "quem está usando esta tag hoje"): `associacoes_tag_equipamento WHERE tag_id = ... AND fim IS NULL`.
- **Vínculo NO MOMENTO da leitura** (o caso correto para rastrear uma `leitura_bruta` específica, que é o que esta seção deveria descrever): usar o intervalo meio-aberto `[inicio, fim)` documentado na seção da tabela `associacoes_tag_equipamento` —

```sql
  SELECT equipamento_id FROM associacoes_tag_equipamento
  WHERE tag_id = :tag_id
    AND inicio <= :lido_em
    AND (fim IS NULL OR fim > :lido_em)
```

  **Usar `fim IS NULL` sozinho aqui é um erro**: depois de reassociar uma tag (ex.: Tag A sai da cadeira em março e vai pra maca), uma leitura antiga (de janeiro, quando a tag ainda estava na cadeira) ficaria incorretamente atribuída à maca, porque a maca é que tem a associação `fim IS NULL` hoje. `fim IS NULL` só responde "qual é o vínculo atual" — nunca "qual era o vínculo no instante T de uma leitura específica".

Uma leitura de EPC não cadastrado (sem nenhuma linha em `associacoes_tag_equipamento`) fica órfã do lado do ativo, mas nunca é perdida — a leitura bruta continua existindo e rastreável até o portal.

**Constraint de banco vs. aplicação:** o `CHECK (fim IS NULL OR fim >= inicio)` garante que cada linha individual tenha um período válido. Impedir períodos **sobrepostos** entre linhas diferentes da mesma tag não é garantido pelo banco nesta migration — é responsabilidade da aplicação sempre fechar a associação anterior (`fim = now()`) antes de abrir uma nova, na mesma transação (ver detalhamento completo na seção da tabela `associacoes_tag_equipamento`, acima).

## 4. Cenários de validação cruzada (para revisão da dupla)

1. **Cadastro:** `tipos_equipamento` → `equipamentos` → `tags` → `associacoes_tag_equipamento` (ativa).
2. **Passagem entre duas zonas (fluxo futuro):** `leituras_brutas` → observações por antena (ISS-014) → detecção de `passagens` (ISS-015) → direção (ISS-016) → `equipamentos.ultima_zona_id/ultima_deteccao_em` (ISS-017) → `historico_movimentacoes` (ISS-018).
3. **Troca de tag:** associação ativa antiga recebe `fim = now()`; nova linha criada para a nova tag no mesmo equipamento — o equipamento mantém histórico completo de EPCs já usados, sem perder o histórico de movimentação anterior (que referencia o equipamento, não a tag).
4. **Correção manual:** admin altera `equipamentos.ultima_zona_id` diretamente → `historico_movimentacoes` recebe linha com `passagem_id = NULL` e `origem_registro='correcao_manual'` → `auditorias` recebe entrada com `dados_antes`/`dados_depois` e `usuario_id` preenchido.

## 5. Decisões e dúvidas pendentes do HUPAA

- **Nomenclatura oficial de andares/setores:** o hospital já tem uma codificação própria (ex.: "4º andar — Ala Norte")? Alinhar `zonas.nome` a essa nomenclatura desde já evita retrabalho depois.
- **Retenção de `leituras_brutas` (RNF-015):** **TBD com HUPAA**; sem expurgo automático. Tamanho de armazenamento exige medição das linhas e índices reais.
- **Backup/recuperação (RNF-011):** confirmar qual plano do Neon garante quantos dias de *point-in-time recovery* — hoje ainda não definimos RPO/RTO formal.
- **Residência de dados:** já sinalizado no documento de hospedagem — se o HUPAA exigir dado em território nacional, a região `AWS US East 2 (Ohio)` do Neon precisa ser revista.

## 6. O que isso desbloqueia
Esta modelagem alimenta diretamente **ISS-002c** (migrations) e orienta a implementação de **ISS-008 a ISS-018** (cadastro base + inferência de passagem).
