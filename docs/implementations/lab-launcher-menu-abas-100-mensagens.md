# Menu, observadores identificados e roteiro de 100 mensagens

## Problema e importância para o MVP

No Windows, a abertura de consoles separados dificultava identificar MQTT,
ingestor e banco. O observador do banco podia falhar sem que o launcher
percebesse. O comando direto também pulava o menu de cenários. Para ensaiar a
Sprint 2 sem o leitor físico, poucas leituras não mostravam com clareza a
aproximação, a permanência e a passagem de um mesmo item pelo portal.

## O que foi feito

- `python -m tools.lab_launcher` abre o menu interativo e limpa a tela antes de
  apresentar as quatro escolhas. Flags continuam disponíveis para automação.
- Com Windows Terminal disponível, os observadores abrem em abas nomeadas
  **MQTT**, **Ingestor** e **Banco**. Sem ele, abrem janelas `cmd.exe` com títulos.
  Cada observador sinaliza quando iniciou; se uma aba não iniciar, o launcher
  tenta recuperar o observador em uma janela e informa a falha persistente.
- O roteiro sintético padrão publica 100 mensagens de um EPC: 15 durante a
  aproximação da antena 1, 45 enquanto o item permanece parado, 10 na saída
  da antena 1 e 30 durante a passagem pela antena 2. O publicador mostra cada
  envio e a etapa correspondente. `--count` aumenta o número de itens e
  `--messages` ajusta a quantidade por item.
- A verificação final espera que todas as 100 leituras sejam persistidas e
  confere a passagem, o movimento e a última zona quando aplicáveis.

O JSON sintético compacto reproduz os campos vistos no terminal do leitor, na ordem
`epc`, `rssi`, `antenna`, `timestamp`, sem `readerid` no corpo. O leitor é
identificado pelo tópico MQTT. `timestamp` é string de sete dígitos e RSSI
varia ilustrativamente na faixa observada, de -6700 a -5700. Esses valores
não substituem a validação da temporização e do sinal do leitor físico.

## Como verificar

No ambiente virtual com as dependências instaladas, execute:

```bash
python -m tools.lab_launcher
```

Escolha **1** para o ensaio local sintético. O terminal principal mostra o
progresso e os resultados; as abas mostram MQTT, ingestor e banco. Ao terminar,
use `Ctrl+C` no terminal principal ou `python -m tools.lab_launcher stop`.

## Validação

O menu foi aberto em um terminal interativo e mostrou as quatro opções após
limpar a tela. Ruff e a suíte com PostgreSQL descartável passaram (859 testes,
5 pulados). Em broker e banco isolados, o publicador enviou 100 mensagens;
as 100 leituras foram persistidas e a verificação concluiu passagem,
movimentação e última zona. Os argumentos das abas Windows e dos terminais
Ubuntu foram cobertos por testes automatizados; a apresentação visual nesses
terminais ainda depende do ensaio no computador do usuário.
