# ISS-019 — Busca operacional de ativos

## Issue e importância para o MVP

A ISS-019 ([issue #21](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/issues/21)) implementa o RF-014: a equipe deve localizar equipamentos por nome,
patrimônio, tipo, EPC, status e última zona conhecida. A consulta junta o cadastro
das ISS-008/009/010/011 à projeção da ISS-017, sem inferir posição a partir de
uma leitura isolada. O estado temporal reutiliza integralmente a regra provisória
da ISS-022 (`RFID_RECENCY_THRESHOLD_MINUTES`, default de 30 minutos). A consulta
serve ao dashboard e aos dois modos de mapa da interface.

## Contrato HTTP

`GET /api/ativos` retorna `200` com `items`, `total`, `page` e `page_size`.
Todos os filtros são opcionais e combinados com **AND**:

| Parâmetro | Regra |
| --- | --- |
| `q` | Trecho sem distinção de caixa em nome ou identificador interno; 1 a 120 caracteres. `%` e `_` são literais. |
| `tipo` | ID positivo do tipo de equipamento. |
| `epc` | EPC exato da associação **ativa**, hexadecimal de 8 a 32 caracteres pares, normalizado em maiúsculas. |
| `status` | `disponivel`, `atencao`, `offline`, `fora_de_servico` ou `nunca_detectado`. |
| `zona` | ID positivo da última zona conhecida. |
| `page`, `page_size` | Página a partir de 1; tamanho 1 a 100, default 20. Página além do fim retorna `items: []` e `total` preservado. |
| `sort` | `nome` (default), `-nome`, `ultima_deteccao_em`, `-ultima_deteccao_em`; ID ascendente desempata. Datas nulas ficam por último. |

Exemplo:

```http
GET /api/ativos?tipo=2&zona=4&status=atencao&page=1&page_size=20
```

```json
{
  "items": [{
    "id": 42,
    "nome": "Maca 07",
    "identificador_interno": "PAT-3170",
    "tipo": "Maca",
    "tipo_id": 2,
    "epc": "E2000017221101441890A003",
    "status": "atencao",
    "ultima_zona": {"id": 4, "nome": "Centro Cirúrgico", "referencia_planta": "zona-2", "andar": "2º andar", "setor": "Bloco B", "caminho": "2º andar → Bloco B → Centro Cirúrgico"},
    "ultima_deteccao_em": "2026-09-26T12:00:00Z",
    "localizacao_desatualizada": true
  }],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

Os campos `andar`, `setor` e `caminho` foram acrescentados na ISS-021; veja
[o contrato temporal e o acesso ao histórico](iss-021-ultima-localizacao-interface.md).

Um EPC válido sem vínculo ativo retorna `200` e `{"items": [], "total": 0,
"page": 1, "page_size": 20}`. Dados com formato inválido, filtros fora da faixa,
status ou ordenação desconhecidos retornam `422`. Falha de banco resulta em erro
de servidor; o frontend mostra uma mensagem e botão de nova tentativa.

### Semântica dos estados

1. Sem `ultima_deteccao_em`: `nunca_detectado`, zona/timestamp nulos e
   `localizacao_desatualizada: null`, mesmo se o cadastro estiver inativo.
2. Detectado com cadastro inativo: `fora_de_servico` (tradução da baixa lógica
   cadastral, **não** diagnóstico técnico de manutenção).
3. Detectado com cadastro ativo e localização acima do limite da ISS-022:
   `atencao`, `localizacao_desatualizada: true`.
4. Detectado com cadastro ativo e localização recente: `disponivel`,
   `localizacao_desatualizada: false`. O termo representa apenas o estado
   derivado disponível para consulta, **não** disponibilidade clínica validada.

O modelo ainda não mede conectividade; `status=offline` é aceito pelo contrato e
retorna lista vazia até existir telemetria correspondente. Não se inventa um
estado offline a partir de silêncio RFID. A regra formal de estados operacionais
deve ser refinada em issue futura com a equipe do HUPAA.

## Implementação e frontend

A query única usa joins da associação EPC ativa, tipo e última zona; não há
N+1 por item. Os filtros são parametrizados pelo SQLAlchemy e o campo de
recência é derivado com o mesmo horário de referência em toda a requisição.
`tags.epc` já tem índice único; `equipamentos.ultima_zona_id` já tinha índice;
os índices de `tipo_id` e `ultima_deteccao_em` foram adicionados pela migration
`b019a1b2c3d4`. A busca textual parcial pode exigir `pg_trgm` se o volume
real crescer; essa extensão não é presumida no Neon neste MVP.

O dashboard chama a API para filtros, contadores e paginação real. Tabela e
drawer mostram a badge “Localização pode estar desatualizada”. Os mapas
consultam o catálogo paginado e agrupam ativos na zona cujo
`zonas.referencia_planta` foi explicitamente configurado como `zona-1`,
`zona-2`, `zona-3`, `sala-a` ou `sala-b`; o marcador representa o **centro
esquemático da zona**, nunca coordenada do equipamento. Ativos sem detecção
ficam em “Ainda não detectados”, fora da planta; zonas sem referência ficam
em lista separada. O campo EPC pode ser consultado no dashboard e nos dois
modos de mapa. Não há consulta ao broker nem substituição da simulação física
por telemetria não validada.

Em desenvolvimento, iniciar a API em `127.0.0.1:8000` e o Vite em `:5173`;
o proxy encaminha as rotas necessárias. Em hospedagem separada, definir
`VITE_API_BASE_URL` na compilação e configurar CORS no backend conforme a
origem escolhida. Nenhuma credencial é embutida no frontend.

## Validação e desempenho

`tests/test_busca_ativos.py` usa PostgreSQL local descartável e cobre filtros
isolados, combinação AND, paginação inclusive página vazia, nunca detectado,
EPC desconhecido e validação HTTP. `frontend/src/test/App.test.tsx` cobre
busca EPC real via `fetch`, badge, drawer, mapa sem marcador inventado e erro.

O script reproduzível `docs/experiments/iss019-explain.sql` insere 5.000 ativos
e 2.500 EPCs **sintéticos** num banco descartável, roda `ANALYZE` e dois
`EXPLAIN (ANALYZE, BUFFERS)`. Em PostgreSQL 16 local, a consulta por tipo,
zona e recência retornou 20 linhas em **2,456 ms** e usou
`ix_equipamentos_ultima_zona_id` (2,054 ms de planejamento); a busca por EPC
retornou uma linha em **0,173 ms** e usou `tags_epc_key` e `uq_tag_ativa`
(0,449 ms de planejamento). São medidas de banco com cache local, não SLA de
API/rede nem substituto da validação no Neon e HUPAA. O `EXPLAIN` segue a forma
da consulta principal; variações com outros filtros podem escolher planos
diferentes.

Na base atual, `python -m pytest -q` com `TEST_DATABASE_URL` local descartável
passou com **874 testes aprovados, 5 pulados e 90 subtestes aprovados**;
`python -m ruff check --config config/ruff.toml --select E4,E7,E9,F,I .` passou. No frontend,
`npm run build` e `npm test` passaram (4 testes). A suíte inclui regressões
do pipeline de ingestão lógico; os 5 pulos dependem de infraestrutura não
disponível neste ambiente. A revisão pela dupla Thiego/Otávio e a validação
física no HUPAA são etapas humanas pendentes.
