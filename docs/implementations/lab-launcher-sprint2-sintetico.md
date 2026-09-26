# Correção dos observadores e ensaio sintético da Sprint 2

## Problema e importância para o MVP

No Windows, o Windows Terminal interpretava a linha PowerShell destinada aos
observadores como nome de executável. As três abas falhavam com `0x80070002`
e mostravam mensagens sobre PSReadLine. Além disso, o publicador emitia só
duas mensagens por EPC, e o seed não associava EPCs sintéticos a equipamentos.
Assim, o laboratório não mostrava claramente o percurso completo da Sprint 2:
leitura bruta, debounce, passagem, direção, movimento e última zona.

## O que foi feito

- No Windows, os observadores agora abrem em três consoles `cmd.exe` separados,
  por meio de um script estático, sem passar um comando PowerShell composto ao
  Windows Terminal. O console fica aberto para leitura dos erros.
- No Ubuntu, a abertura continua usando `gnome-terminal`, `konsole`, `xterm`,
  `x-terminal-emulator` ou `tmux`; os comandos são montados como argumentos
  separados e testados sem depender de um shell do Windows.
- O cenário sintético padrão usa três EPCs estáveis e três leituras por antena
  para cada EPC, com pausa entre os lados do portal. A saída identifica cada
  mensagem publicada.
- Antes da publicação, o seed cria ou reutiliza um equipamento de laboratório
  e sua associação temporal por EPC. Vínculos já existentes não são alterados.
- O publicador emite os campos JSON atualmente aceitos pelo adapter EZ700 e,
  por padrão, um contador sintético crescente. O tempo canônico é o horário de
  recebimento; o contador permanece na auditoria. Isso não substitui validação
  física do relógio ou do protocolo do leitor.
- O terminal do banco acompanha leituras, passagens, status de direção,
  movimentos e última zona. O terminal principal consulta o banco após a
  publicação e informa o resultado de cada EPC ou a etapa que ficou pendente.

## Como verificar

```bash
python -m tools.lab_launcher start --env local --source synthetic --reuse
```

Com os padrões, são esperadas 18 leituras publicadas, seis por EPC. Cada EPC
deve produzir uma passagem `confirmed` A→B, um movimento automático e última
zona igual à zona B. `--single` valida apenas persistência de leituras. Os
parâmetros temporais continuam experimentais; a leitura física no HUPAA ainda
é necessária para calibrá-los e confirmar o comportamento real do Identix EZ700.

## Validação desta correção

Ruff e a suíte geral passaram; os testes que exigem serviços externos foram
pulados quando não estavam configurados. Com PostgreSQL e Mosquitto temporários
em portas isoladas, 33 testes direcionados passaram usando o banco real. No
ensaio MQTT ponta a ponta, 18 mensagens produziram 18 leituras brutas, três
passagens A→B confirmadas, três movimentos e projeção de zona B para os três
equipamentos. Uma segunda execução reutilizou o vínculo do primeiro EPC e
produziu outra passagem e movimento. O script `cmd.exe` dos observadores foi
executado localmente com `--help`, sem conectar aos serviços do usuário. A
montagem dos comandos Ubuntu foi coberta por teste; a abertura gráfica no
Ubuntu e a abertura visual dos novos consoles no Windows dependem de ensaio no
ambiente do usuário.
