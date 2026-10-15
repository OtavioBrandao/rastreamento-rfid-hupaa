# Guia de ambiente e evidências visuais

## Problema e importância para o MVP

As instruções de configuração estavam concentradas no guia detalhado, e a página
inicial não mostrava visualmente o fluxo operacional. Isso dificultava iniciar
o laboratório e compreender a relação entre leituras, passagem e última zona.

## Solução

O README passou a explicar a cópia dos perfis, os campos MQTT, as URLs de banco,
o publicador separado e os ajustes do ambiente local. Os modelos de publicador
externo usam host fictício para orientar a configuração.

Uma demonstração isolada gerou dados com o publicador do simulador e percorreu
o pipeline real. Foram adicionadas capturas de dashboard, planta EASY, leituras
por antena e detalhe com histórico. A galeria explica a origem sintética e inclui
registro JSON sanitizado, sem credenciais, dados hospitalares ou respostas HTTP
fabricadas. A evidência corresponde à execução de software, sem medição RF.

## Validação

Capturas conferidas visualmente e comparadas com as consultas SQL de passagens,
movimentos e projeção. Testes de configuração e Compose aprovados, além da
verificação de links locais, perfis ignorados e `git diff --check`.

Consulte a [galeria e o procedimento](../experiments/galeria-pipeline.md).
