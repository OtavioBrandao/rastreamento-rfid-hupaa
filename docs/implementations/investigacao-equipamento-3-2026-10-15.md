# Investigação — equipamento 3 no ensaio de 15/10/2026

## Escopo e importância

Investigar por que o equipamento 3 permaneceu com a zona do dia anterior, apesar
de estar sendo lido em A. É preciso separar presença na antena, evidência de
passagem, direção confirmada e atraso de processamento antes de propor um hotfix.
Esta investigação não altera código nem dados da inferência.

## Fontes e identificação

Consultas somente de leitura no banco configurado em `.env.cloud`, logs do
ingestor e replay em memória dos componentes existentes. O equipamento em
atividade é o **ID 10**, nome “Equipamento 3”, EPC terminado em `B3B50EDF`.
Existe outro cadastro com o mesmo nome (ID 6), sem zona confirmada; a análise
acompanha o EPC do ID 10, sem confundir os dois cadastros.

Todos os horários abaixo são de **Maceió/São Paulo (UTC−03:00)**.

## O que aconteceu

| Momento | Evidência | Resultado |
|---|---|---|
| 14/10, 09:38:06.473 | Passagem #76, A→B, evidências separadas por 1.440 ms | Zona B confirmada; era a localização anterior ao ensaio atual. |
| 15/10, 01:57:46.240–01:57:46.267 | Última leitura de B e primeira de A separadas por **27 ms**; passagem #82 | `ambiguous`, regra `temporal_proximity_v1`; sem nova movimentação ou atualização de zona. |
| 15/10, 01:58:27.749–01:58:28.289 | Quatro leituras em B, seguidas de retorno a A às 01:58:28.771 | Nenhuma nova passagem; ver replay abaixo. |
| 15/10, 01:59:01.295 | Passagem #88, A→B, intervalo entre evidências de 471 ms | Direção confirmada; histórico gravado às 01:59:08.094. |
| 15/10, 01:59:14.149 | Passagem #89, B→A, intervalo entre evidências de 475 ms | Direção confirmada; histórico gravado às 01:59:20.358; projeção em Zona A. |

A tolerância de ambiguidade configurada era **100 ms**. Os 27 ms da primeira
travessia não dão direção confiável segundo a regra vigente. Permanecer em A
continua gerando leituras de presença, mas não converte essa direção ambígua em
uma localização confirmada. Por isso o horário do dia 14 ficou visível até uma
travessia posterior confirmada.

## Atraso e ordenação das observações

Os logs mostraram atraso variável da inferência: às 01:58:47 foram processadas
observações de A de 01:58:26–01:58:30 e, em seguida, observações de B de
01:58:27–01:58:28. Há observações entre antenas entregues fora da ordem temporal;
o detector pode suprimi-las como sobreposição com uma âncora mais nova.

Esse é um ponto de robustez a investigar separadamente, mas não basta para
atribuir a ausência de passagem neste caso a um bug: a volta de A ocorre dentro
da janela de proteção contra reflexão da breve leitura em B.

## Replay e conclusão

Foram reprocessadas **206 observações** do EPC, com o `PassageDetector` existente,
janela de 3 s, refratário de 1 s e a verificação de origem ativa reproduzida a
partir das leituras brutas (grace de 300 ms e hold de 1 s). O replay não grava
passagens no banco e confirma as propostas apenas no estado em memória.

- **Ordem dos logs:** reproduziu exatamente as três propostas #82, #88 e #89.
- **Ordenação por tempo do evento:** produziu as mesmas três propostas; a breve
  visita a B foi rejeitada duas vezes pela verificação de origem ativa/reflexão.

Assim, reordenar as observações sozinho **não recuperaria essa passagem curta**.
O episódio observado combina primeira direção ambígua, retorno curto rejeitado
pelas proteções e atraso de inferência. As duas travessias posteriores foram
persistidas corretamente, com latência de aproximadamente 6,8 s e 6,2 s antes do
próximo polling da interface.

**Não foi demonstrado um bug na regra de direção ou na atualização da última
zona neste episódio.** A ordenação entre antenas e o atraso variável merecem
um ensaio específico antes de qualquer ajuste. Não se deve reduzir tolerâncias
ou remover a proteção contra reflexão com base apenas nesta simulação.

Nenhum hotfix da lógica RFID foi implementado; leituras, histórico e projeção
foram preservados. A revisão geral do README/documentação não integra esta entrega.
