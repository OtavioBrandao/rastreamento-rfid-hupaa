# Correção da aba Banco no launcher do Windows

## Problema e importância para o MVP

Em um ensaio local, a aba Banco exibiu `"" não é reconhecido como um comando`.
O script recebia o caminho do Python por `LAB_WATCH_PYTHON`, variável definida
para cada chamada do Windows Terminal. A variável podia chegar vazia na aba;
nesse caso o observador não iniciava e o operador perdia a visão das leituras,
passagens, movimentações e última zona, mesmo com o ingestor funcionando.

## O que foi feito

- O caminho do Python, o tipo de observador e o título passam como argumentos
  explícitos para `watch_windows.cmd`. As três abas são solicitadas em uma única
  chamada do Windows Terminal, com títulos MQTT, Ingestor e Banco.
- Os observadores leem a configuração de execução de um arquivo temporário em
  `.lab_launcher/`, ignorado pelo Git. Assim, a abertura das abas não depende
  de variáveis herdadas do Windows Terminal, e credenciais não aparecem na linha
  de comando. O arquivo é removido por `stop`, `Ctrl+C` ou ao iniciar outra sessão.
- O observador Banco confirma a conexão e mostra periodicamente que continua
  monitorando, inclusive enquanto não há novas leituras.

## Validação

Os testes automatizados verificam a chamada única das três abas, os argumentos
explícitos, a recuperação de uma aba que falhe e a remoção do arquivo de sessão.
Em Windows, `cmd.exe` executou o script com o ambiente do Windows Terminal
ausente: o observador Banco iniciou, conectou ao PostgreSQL e exibiu o estado
de monitoramento. A apresentação visual final das abas ainda deve ser conferida
no ensaio interativo do usuário.
