# ISS-021 — Última localização e horário da detecção

## Issue e importância para o MVP

A [issue #23](https://github.com/OtavioBrandao/rastreamento-rfid-hupaa/issues/23)
implementa RF-017, requisito Must. Uma zona sem andar e setor é ambígua para
quem consulta o inventário. Um horário alterado pelo fuso do navegador ou pelo
tempo de processamento da pipeline compromete a confiança na última detecção.
A localização continua aproximada por zona e depende de passagem confirmada.

## Contrato da API

`GET /api/ativos` mantém filtros e paginação da ISS-019. Quando há detecção,
`ultima_zona` inclui os campos anteriores (`id`, `nome`,
`referencia_planta`) e acrescenta `andar`, `setor` e `caminho`. O caminho usa
os nomes cadastrados na hierarquia ISS-011, separados por ` → `, por exemplo:

```json
{
  "ultima_zona": {
    "id": 214,
    "nome": "Sala 214",
    "referencia_planta": null,
    "andar": "2º andar",
    "setor": "Bloco B",
    "caminho": "2º andar → Bloco B → Sala 214"
  },
  "ultima_deteccao_em": "2026-09-22T12:00:01Z"
}
```

Sem detecção, `ultima_zona` e `ultima_deteccao_em` continuam `null`; o
estado `nunca_detectado` permanece explícito. A busca carrega setor e andar
junto com a zona, sem consulta adicional por ativo.

O histórico da ISS-018 já estava persistido e disponível em
`GET /equipamentos/{id}/movimentacoes?page=1&size=20`. A rota devolve
`items`, `page`, `size`, `total` e `pages`, ordenados por
`movimentada_em DESC NULLS LAST, id DESC`; páginas vão de 1 em diante e
`size` aceita 1 a 100. Equipamento inexistente retorna 404. O drawer agora
oferece “Ver histórico completo”, consulta essa rota sob demanda e permite
navegar entre páginas. Mostra origem, destino, instante da movimentação e
justificativa de correção manual. Falha da consulta não conserva uma página
anterior como se fosse atual.

## Contrato temporal

- **Ingestão:** timestamp válido no payload simulado é normalizado para UTC;
  a leitura bruta guarda `lido_em` como `TIMESTAMP WITH TIME ZONE`. O formato
  e o relógio do EZ700 físico continuam pendentes de validação no HUPAA.
- **Inferência:** `passagens.detectada_em` vem do último `last_seen_at` das
  observações que confirmaram a passagem. O histórico automático usa esse
  instante em `movimentada_em`; `registrado_em` marca o processamento. A
  projeção `equipamentos.ultima_deteccao_em` usa `movimentada_em`.
- **Banco:** PostgreSQL usa `TIMESTAMP WITH TIME ZONE`, que preserva o
  instante. O offset da sessão de leitura pode variar; a API converte os
  instantes expostos para UTC antes de serializar. Não há migração de dados.
- **API:** `ultima_deteccao_em`, `movimentada_em`, `registrado_em` e
  `recebido_em` de leituras do laboratório são emitidos em UTC com offset.
- **Interface:** tabela, drawer, histórico e leituras do laboratório formatam
  o instante em `America/Maceio`, independentemente do fuso do navegador.
  Exemplo: `2026-09-22T12:00:01Z` aparece como `22/09/2026 09:00`.
  A interface mostra minuto, enquanto a API mantém a precisão do instante.

## Validação e limites

O teste integrado `test_full_pipeline_projects_only_confirmed_passages` injeta
duas mensagens MQTT simuladas no receptor, passa por persistência, debounce,
passagem, direção e projeção, e consulta a busca e o histórico via HTTP.
Ele compara o horário da última detecção com o timestamp da segunda leitura
e confirma que `registrado_em` é diferente. A variante ambígua não projeta
zona. `tests/test_busca_ativos.py` verifica o caminho e a serialização UTC
inclusive com sessão PostgreSQL em `America/Maceio`. O teste do frontend
verifica o caminho na tabela e no drawer, o horário hospitalar e a abertura
do histórico. A validação física do EZ700 continua pendente.

O proxy de desenvolvimento Vite encaminha `/equipamentos` para a API. Em
implantação com origens separadas, `VITE_API_BASE_URL` e CORS seguem a mesma
configuração das demais rotas.

Na validação local com PostgreSQL 16 descartável, a suíte Python completa
terminou com **880 aprovados, 5 pulados e 90 subtestes aprovados**. O build do
frontend e os 5 testes Vitest passaram. Ruff e `git diff --check` passaram.
