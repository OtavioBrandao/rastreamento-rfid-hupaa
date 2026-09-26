# Verificação da fila de ingestão no ensaio externo sintético

## Problema e importância para o MVP

Na opção 4, um ensaio publicou 100 mensagens no HiveMQ, mas o launcher encerrou
a verificação após 30 segundos com 32 leituras persistidas. Uma 33ª leitura
apareceu durante o encerramento. O log do ingestor mostrou persistências
sucessivas, sem erro de normalização ou banco, e apenas leituras da antena 1
antes do encerramento. A captura do Neon confirmou essas linhas. Portanto, o
ensaio demonstrou publicação e ingestão parcial, mas não chegou à segunda
antena para validar passagem, direção, movimento e última zona.

O ingestor processou esse lote externo mais devagar que a publicação, em torno
de uma leitura a cada 1–2 segundos no trecho registrado. O limite fixo de 30
segundos no verificador interrompeu o contêiner enquanto ainda havia mensagens
na fila MQTT. O PUBACK recebido pelo publicador confirma o recebimento pelo
broker; não confirma o commit de cada leitura no Neon.

## Correção

O verificador acompanha o número de leituras persistidas por EPC. O prazo de
inatividade de 30 segundos recomeça quando esse número cresce; existe também
um limite total de cinco segundos por mensagem esperada mais 30 segundos para
finalizar a inferência. A saída informa os limites e o progresso. Se a fila
parar, o erro distingue ausência de progresso do esgotamento do prazo total.
Como a sessão MQTT pode entregar mensagens pendentes de um ensaio interrompido,
a conferência filtra as leituras e as evidências da passagem pelo intervalo do
contador de sete dígitos sorteado para esta execução. O contador original já é
conservado em `leituras_brutas.dados_origem`; nenhum campo novo é enviado ao
broker. Enquanto a fila anterior está sendo drenada, novas linhas no banco
também renovam o prazo de inatividade, mas não contam para as 100 leituras
atuais. O JSON sintético, a ordem das 100 mensagens e as regras da Sprint 2
permanecem iguais.

## Diagnóstico da Sprint 2

As observações de debounce registradas nesse trecho tinham uma leitura cada:
o tempo canônico do contador EZ700 é o instante de recebimento pelo ingestor,
e o intervalo entre mensagens processadas excedeu a janela inicial de 250 ms.
Isso é coerente com a configuração experimental da ISS-014; não demonstra
defeito na regra de debounce. Como nenhuma leitura da antena 2 foi processada
antes de o launcher encerrar o contêiner, não há evidência desse ensaio para
afirmar falha das ISS-015, ISS-016, ISS-017 ou ISS-018. Uma nova execução até
o fim é necessária para concluir o percurso em HiveMQ e Neon. Os parâmetros
temporais continuam pendentes de calibração com o leitor físico no HUPAA.

## Validação

Testes automatizados simulam uma ingestão que progride por mais de 30 segundos,
outra que para após duas leituras, fila antiga pendente e a seleção das
evidências pelo contador do ensaio. Um teste da ISS-015 confirma que
observações isoladas processadas no
ritmo observado ainda podem produzir a passagem quando a antena 2 chega dentro
da janela temporal. O ensaio externo real depende de repetir a opção 4 com o
HiveMQ e a branch de teste do Neon.
