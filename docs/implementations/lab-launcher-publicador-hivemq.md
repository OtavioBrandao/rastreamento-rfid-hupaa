# Perfil de publicação no teste externo sintético

## Problema e importância para o MVP

Na opção 4 do launcher, o ingestor conectava ao HiveMQ, mas a primeira leitura
sintética podia terminar com `broker não confirmou a leitura sintética`. O
launcher reutilizava, por padrão, as credenciais MQTT do ingestor para publicar.
No perfil de laboratório documentado, essa identidade tem permissão somente de
assinatura; o leitor sintético precisa de outra credencial com permissão Publish
no tópico `easy/dev/hupaa/portal-01/reader-01/readings`.

Uma conexão MQTT bem-sucedida confirma autenticação, não autorização para
publicar. Sem PUBACK, a mensagem não pode ser contada como publicada, e o teste
da Sprint 2 não deve seguir como se tivesse dado certo.

## O que foi feito

- O cenário externo sintético agora seleciona `config/environments/.env.cloud.reader-01` quando o
  arquivo existe. Sem ele, o menu pergunta pelo arquivo da credencial de
  publicação; execução sem interação exige `--publisher-env-file`.
- O perfil é validado antes de construir ou iniciar serviços: precisa ter
  usuário, senha e tópico exato, sem curingas. A credencial deve ser diferente
  da usada pelo ingestor. Nenhuma senha é mostrada no terminal ou passada em
  argumento de processo.
- Falhas de enfileiramento, ausência de PUBACK em 10 segundos e desconexão
  antes do PUBACK agora produzem mensagens distintas. A mensagem de desconexão
  orienta a conferir a permissão Publish e o tópico, sem afirmar que a ACL é a
  única causa possível.

## Como executar

No Ubuntu, mantenha `config/environments/.env.cloud` para o ingestor e um arquivo privado
`config/environments/.env.cloud.reader-01` para o publicador, com credencial Publish e
`MQTT_TOPIC=easy/dev/hupaa/portal-01/reader-01/readings`. O arquivo fica fora
do Git. Pelo menu, escolha **4**; o perfil padrão será encontrado
automaticamente. Para outro nome de arquivo:

```bash
./.venv/bin/python -m tools.lab_launcher start --env managed --source synthetic \
  --publisher-env-file config/environments/.env.cloud.reader-01
```

O ensaio real no HiveMQ deve confirmar a ACL configurada no cluster. Os testes
automatizados cobrem a seleção do perfil e a classificação de uma desconexão
sem PUBACK, sem usar credenciais externas.
