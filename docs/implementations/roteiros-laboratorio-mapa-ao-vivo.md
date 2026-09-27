# Roteiros do laboratório e leituras no mapa EASY

## Importância para o MVP

O ensaio com uma tag não exercita cruzamentos simultâneos nem a permanência de
um equipamento em uma sala enquanto outro circula. Estes roteiros permitem
observar, no mapa, a diferença entre **leitura da antena** e **última zona
confirmada** pela inferência de passagem.

## Implementação

- O launcher oferece três roteiros após escolher qualquer um dos quatro modos.
  Nos modos sintéticos publica os percursos; nos físicos mostra as instruções de
  movimentação. `--scenario` permite executar sem menu. Os EPCs padrão dos
  roteiros 2 e 3 terminam em 02 e 03.
- O seed associa os EPCs a equipamentos e grava `sala-a`/`sala-b` nas referências
  de planta das zonas do laboratório. Uma referência divergente causa erro em
  vez de ser sobrescrita.
- A conferência do ensaio conta leituras do contador reservado, valida a ordem
  das direções confirmadas, o movimento da última passagem e a zona final.
- `GET /api/laboratorio/leituras?after_id=0&limit=30` retorna as leituras mais
  recentes do portal do laboratório em ordem crescente. Com `after_id>0`,
  retorna apenas leituras posteriores ao cursor. Aceita `epc` exato; `limit`
  é limitado a 100 e parâmetros inválidos recebem 422.

```json
{
  "items": [{
    "id": 123,
    "epc": "E2804C414200000000000002",
    "antena_porta": 1,
    "recebido_em": "2026-09-26T12:00:00+00:00"
  }],
  "next_id": 123
}
```

O mapa EASY consulta esse endpoint a cada segundo, registra EPC e antena e
pulsa o marcador da antena para cada leitura. Consulta `/api/ativos` a cada
dois segundos para atualizar os marcadores de **zona confirmada**. Um ativo
sem detecção continua fora do mapa, na lista “Ainda não detectados”. O campo
de EPC da página filtra ambas as consultas. Falhas de atualização mostram uma
mensagem e deixam a última posição conhecida visível.

## Validação

Execute a suíte do launcher/API com um diretório temporário gravável e a suíte
do frontend. Testes de banco exigem `TEST_DATABASE_URL` para PostgreSQL local
descartável; a fixture não usa `DATABASE_URL` gerenciado. Os testes de geração
validam direções e intercalamento; os testes HTTP validam cursor, escopo do
portal e parâmetros inválidos. A interface testa o log real, pulso e zona
confirmada. Um ensaio MQTT físico/externo ainda depende do broker e do leitor
disponíveis no laboratório.
