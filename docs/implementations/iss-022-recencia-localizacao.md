# ISS-022 — Recência da última localização

## Problema e importância para o MVP

A Issue #24 classifica a informação de localização aproximada de um equipamento.
Uma zona registrada há muito tempo não pode parecer uma posição atual: o ativo
pode ter sido movido sem nova detecção, induzindo a equipe hospitalar ao erro.
O estado complementa a projeção da ISS-017 e não altera o histórico nem a zona.

## Regra temporal

O backend usa `equipamentos.ultima_deteccao_em`, o horário UTC atual da API e
um limite positivo configurável. A função pura `classify_recency` recebe os três
valores explicitamente. Timestamps devem conter fuso horário; a comparação de
instantes aceita fusos diferentes e independe do fuso da máquina.

| Última detecção | Tempo decorrido | `estado_recencia` |
| --- | --- | --- |
| `null` | não aplicável | `nunca_detectada` |
| registrada | menor ou igual ao limite | `recente` |
| registrada | maior que o limite | `desatualizada` |

O limite é **inclusivo**: com 30 minutos, 29m59s e 30m00s são `recente`;
30m00s mais um microssegundo é `desatualizada`. Um equipamento nunca detectado
não recebe zona inventada. O estado é derivado em cada consulta, sem coluna nova,
migration ou escrita: ele pode mudar apenas pela passagem do tempo.

## Configuração provisória do MVP

`RFID_RECENCY_THRESHOLD_MINUTES` define o limite em minutos inteiros positivos
no ambiente **do processo da API**. Seu default provisório é `30`. Os templates
`.env.example`, `.env.local.example` e `.env.cloud.example` mostram esse valor;
o operador precisa exportá-lo para o processo da API ao iniciar o FastAPI. Um
valor ausente usa o default; valores vazios, não inteiros, zero ou negativos
falham explicitamente. Alterar a variável não exige mudar código.

**30 minutos não é um parâmetro validado pelo HUPAA.** A calibração definitiva
depende de observação operacional, da política de uso dos equipamentos e da
validação física prevista na ISS-031. Não se pressupõe comportamento do EZ700.

## Contrato da API e relação com o dashboard

As respostas já existentes de `POST /equipamentos`, `GET /equipamentos`,
`GET /equipamentos/{id}`, `GET /equipamentos/por-identificador/{identificador}`,
`PATCH /equipamentos/{id}` e operações de ativação incluem
`estado_recencia` e `ultima_deteccao_em`. A listagem calcula um único horário
de referência UTC por requisição e usa a coluna já carregada de cada
equipamento, sem consulta adicional por item. A data serializada mantém o fuso.

O dashboard demonstrativo da ISS-032 já recebe um estado pronto e o
`StatusBadge` mostra texto e símbolo para os três casos; um teste explicita
esse contrato visual. A tradução dos valores da API para os tipos de tela e o
fetch real pertencem à #62 (ISS-032B). Zona, andar, setor, horário formatado e
componente completo de localização pertencem à #23 (ISS-021).

## Testes e limitações

Na raiz do repositório:

```bash
python -m pytest -q tests/test_recency.py tests/test_api_recency.py
python -m pytest -q
python -m ruff check --select E4,E7,E9,F,I .
cd frontend
npm ci
npm test
npm run build
```

Os testes da regra fixam `now` e cobrem as fronteiras, fusos e configuração
inválida; os testes HTTP verificam listagem, detalhe, limite configurado e a
mudança de estado sem escrita. Os testes de API existentes que dependem de
PostgreSQL exigem `TEST_DATABASE_URL` apontando para banco local descartável.
O dashboard continua com dados fictícios até a integração da #62. O limite
operacional e o comportamento físico do leitor seguem pendentes de validação
com o HUPAA; esta issue não altera debounce, passagem, direção ou MQTT.
