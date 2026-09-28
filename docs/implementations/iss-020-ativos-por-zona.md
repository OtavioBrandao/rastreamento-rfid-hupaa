# ISS-020 — Ativos por última zona conhecida

## Issue e importância para o MVP

A [Issue #22](https://github.com/OtavioBrandao/rfid-hospital-mvp/issues/22)
(RF-015) permite à equipe consultar os equipamentos associados a uma zona. No
MVP, **"disponível em uma zona" significa ter essa zona como última localização
confiável materializada pela ISS-017**. A informação é aproximada por zona: não
representa coordenadas, sinal RFID ativo agora ou presença física garantida.

## Contrato já implementado

`GET /api/ativos?zona=<id>` reutiliza a busca da ISS-019. O backend filtra
`equipamentos.ultima_zona_id` no banco, usando o índice existente. O filtro de
zona do dashboard envia esse parâmetro à API. A resposta
contém `items`, `total`, `page` e `page_size`, com ordenação estável por nome e
ID como desempate (ou pela ordenação solicitada). `page` começa em 1;
`page_size` vai de 1 a 100 e vale 20 por padrão. Página além do fim mantém o
`total` e retorna `items: []`.

Cada item inclui identificação, tipo, EPC ativo se houver, `ultima_zona`,
`ultima_deteccao_em`, `status` e `localizacao_desatualizada`. A recência segue
o limite provisório da ISS-022, cujo padrão é 30 minutos. A consulta sem
`status` inclui tanto localizações recentes quanto desatualizadas. Para mostrar
somente equipamentos ativos com localização recente, combinar `zona` com
`status=disponivel`; `status=atencao` mostra os ativos desatualizados. Um
equipamento inativo já detectado mantém sua última zona e aparece como
`fora_de_servico`; esse estado não implica disponibilidade clínica. Equipamento
nunca detectado não tem zona e não aparece em uma consulta por zona.

`zona` não numérica ou menor que 1 recebe HTTP 422. Um ID positivo sem ativos
retorna HTTP 200 com `items: []` e `total: 0`, inclusive se a zona não existe.
Uma zona inativa também não tem equipamentos associados no fluxo normal: o
cadastro impede inativar zona referenciada. Assim, a busca retorna o mesmo
resultado vazio. A API de consulta não distingue, pelo resultado, zona vazia,
inexistente ou inativa; o cadastro de zonas é a fonte para verificar seu estado.

## Validação sintética desta issue

O fixture `catalog` de `tests/test_busca_ativos.py` agora contém três ativos
na Zona A, dois na Zona B e um nunca detectado. Há itens recentes, um
desatualizado e um equipamento inativo. O teste chama o endpoint HTTP e compara
os conjuntos completos de IDs: A retorna todos e somente seus três ativos;
B retorna todos e somente seus dois ativos. Também verifica unicidade,
`total`, `ultima_zona`, identificação, tipo, horário e recência. Com página de
dois itens, A ocupa duas páginas sem duplicação, e a terceira vem vazia. Após
atualizar a projeção sintética de um equipamento de A para B, a consulta deixa
de listá-lo em A e passa a listá-lo em B. Foram cobertos ainda os filtros de
status, zona inválida, zona inexistente, zona inativa e o nunca detectado.

O cenário testa a consulta da projeção materializada; não simula uma passagem
RFID nem altera as regras de inferência. **Nenhuma validação física com o
Identix EZ700 ou no HUPAA foi realizada nesta issue.**
