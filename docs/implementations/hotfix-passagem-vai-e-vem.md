# Hotfix — passagens em vai e vem contínuo e rejeição de reflexão

## Problema e importância para o MVP

No ensaio físico de 05/10/2026 (20:57–20:59 UTC), uma pessoa atravessou o
portal EASY de A para B e de B para A sem parar por cerca de 2,5 minutos,
carregando a tag `3034000000000C40000000DA` (**CAIXA EZ700**). Pelas leituras
brutas, o lado dominante alternou **26 vezes**. O sistema confirmou **uma**
passagem (A → B às 20:57:17). Depois disso, a tela mostrava a tag lida na
Antena 1 (Zona A) enquanto a última zona confirmada continuava em Zona B.

A latência da passagem detectada foi boa (1,3 s entre a travessia e a
movimentação). O problema era a regra aplicada **depois** dela: o detector
entrava em estado "confirmado" e descartava toda observação seguinte
(`rfid_passage_activity_suppressed`) até a tag ficar **3 s em silêncio**. Como
a tag era lida quase todo segundo, esse silêncio nunca aconteceu e 139
observações foram descartadas. Uma retirada rápida pelo mesmo portal não seria
registrada.

## Análise com replay

As 12.065 leituras do ensaio foram exportadas e reprocessadas pelo
`DebounceProcessor` e pelo `PassageDetector` reais. O replay reproduziu
exatamente a produção: 1 passagem, latência de 1,35 s. Variantes testadas
sobre os mesmos dados:

| Regra | Passagens da tag em movimento (`…0DA`) | Falsas passagens da tag parada (`…012F`) |
|---|---|---|
| Original (3 s de silêncio) | 1, ou seja 25 perdidas | 1 |
| Âncora sem verificação de reflexão | 34 alternando A↔B | 102 |
| Âncora + refratário de 1 s | 28 | 64 |
| **Âncora + refratário 1 s + origem ativa (grace 300 ms, hold 1 s)** | **24, alternância correta** | **10** |

A tag `…012F` ficou parada perto da antena A durante todo o ensaio (cerca de
5 leituras/s em A) e foi lida por B de forma intermitente, quando a pessoa
estava do lado B (reflexão). Sem tratamento, um equipamento estacionado ao
lado do portal trocaria de zona sozinho.

## O que foi feito

`PassageDetector` (`rfid_inference/passage.py`):

1. **Âncora de lado:** após uma passagem, a observação de destino vira a
   âncora. Leituras no mesmo lado só renovam a âncora. Uma observação no lado
   oposto, posterior à âncora, forma a próxima passagem imediatamente, sem
   exigir silêncio. Retorno depois de `RFID_PASSAGE_MAX_INTERVAL_MS` continua
   começando um candidato novo.
2. **Refratário** (`RFID_PASSAGE_REFRACTORY_MS`, padrão 1000): uma observação
   do lado oposto logo após a passagem é ruído de travessia. Também é ignorada
   uma observação do lado oposto que começou antes da âncora (sobreposição
   das antenas).
3. **Origem ainda ativa:** antes de formar a passagem, o detector consulta
   `PassageRepository.origin_active`. Se a antena de origem leu a tag entre
   `início do destino + RFID_PASSAGE_OVERLAP_GRACE_MS` (padrão 300) e
   `fim do destino + RFID_PASSAGE_ORIGIN_HOLD_MS` (padrão 1000), a tag não
   saiu da origem: é reflexão e a passagem é descartada
   (`rfid_passage_origin_still_active`). As leituras brutas já estão gravadas
   quando o debounce finaliza a observação, então a verificação **não
   acrescenta atraso**. O hold de 1 s fica dentro do intervalo já persistido
   (debounce de 250 ms + tolerância de 1 s).

A direção (ISS-016), a última zona (ISS-017) e o contrato do banco não mudaram.

## Limites

- Com a verificação de reflexão, travessias muito curtas, em que a pessoa
  vira no meio do portal, podem não ser confirmadas (24 de cerca de 30 no
  replay). É a troca aceita para não mover equipamentos parados.
- A tag parada ainda gerou 10 passagens em 2,5 min de movimentação intensa ao
  lado dela. Os três parâmetros são configuráveis e devem ser recalibrados no
  HUPAA, com antenas e potência definitivas.
- A verificação usa a antena da observação de origem; um lado com várias
  antenas é tratado pela antena que viu a tag.

## Validação

- `tests/test_passage.py`: vai e vem contínuo confirma todas as travessias;
  refratário e sobreposição; reflexão rejeitada, com e sem passagem anterior;
  retorno após ausência longa. Os testes que fixavam a regra antiga de
  silêncio foram reescritos.
- `tests/test_passage_integration.py`: `origin_active` contra leituras brutas
  no PostgreSQL.
- Replay do ensaio físico (tabela acima) e ingestor local reiniciado com o
  leitor ligado: sem erros, com a rejeição de reflexão atuando.
