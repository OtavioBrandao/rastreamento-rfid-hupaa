# ISS-001 — evidências e aceite

Data: **2026-09-05**. Branch `feat/iss-001-broker-mqtt-gerenciado`.
Base anterior `8a2f424`; baseline: **8/8 testes unitários aprovados**.
Nenhum resultado físico anterior foi reapresentado como validação HiveMQ.
A equipe confirmou nesta sessão: **cluster HiveMQ ainda não criado**.

## Implementado e testado automaticamente

Configuração compartilhada, TLS obrigatório cloud, certificado/hostname,
credenciais obrigatórias, bloqueio de downgrade, tópicos, payload preservado,
validação de campos, tratamento de falhas, redaction de logs/relatório,
Client IDs distintos e probes de autenticação/ACL com negativa explícita.
Os probes foram testados com respostas simuladas; isso não comprova a ACL externa.

| Teste | Ambiente efetivo | Resultado |
|---|---|---|
| Baseline antes de editar | Python Windows | 8 aprovados |
| Suíte final com integração ativada | Python 3.12 Windows, Paho 2.1.0, Docker Desktop | 26 aprovados; 3 TLS pulados por ausência de OpenSSL no PATH Windows |
| Suíte final com OpenSSL | Ubuntu 24.04/WSL, Python 3.12, Paho 2.1.0 | 28 aprovados; integração Mosquitto pulada nesta distribuição |
| Certificado confiável, CA não confiável e hostname incorreto | Servidor TLS efêmero em loopback Ubuntu; **não Mosquitto nem HiveMQ** | 3/3 aprovados, incluídos nos 28 acima |
| Dois simuladores, QoS 1, retain falso, tópicos diferentes, JSONL | Mosquitto 2.1.2 pelo Compose, Windows/loopback | 40 válidas + 1 JSON inválido + 1 incompleta; 42 persistidas |
| Comando de verificação com dois simuladores | Mesmo Mosquitto, localhost:1883 | 20/20 válidas; 10 por tópico; [relatório sanitizado](local-2026-09-05.json) |
| Bash syntax / LF | `bash -n`, Ubuntu; inspeção dos bytes | Aprovados |
| Smoke shell completo no Ubuntu | WSL sem integração Docker habilitada | Pendente por ferramenta local; tentativa não executou o broker |
| TLS + dois simuladores + JSONL no HiveMQ | Broker gerenciado | Pendente: cluster e credenciais ausentes |
| Autenticação, senha inválida e ACL reais no HiveMQ | Broker gerenciado | Pendente |
| Duas redes / leitores físicos | Campo | Pendente |

Os **29 testes distintos** passaram na união das duas execuções; nenhuma falha
ficou aberta na suíte. Não foram 29 testes aprovados em cada sistema.
Os testes TLS locais não são evidência do HiveMQ, e o Mosquitto anônimo em 1883
não foi usado como evidência de TLS, autenticação ou acesso entre redes distintas.

## Reprodução das execuções

No Windows, ambiente virtual `.venv`, com o Mosquitto já iniciado:

```powershell
$env:RUN_MQTT_INTEGRATION='1'
& .venv/Scripts/python.exe -m unittest discover -s tests -v
& .venv/Scripts/python.exe -m rfid_ingestion.verification --env-file config/environments/.env.local --publisher-env config/environments/.env.local.reader-01 --publisher-env config/environments/.env.local.reader-02 --seconds 10 --count 10 --network windows-docker-loopback --report data/iss001-local.json
```

Os perfis dos publicadores são cópias locais com Client IDs e tópicos individuais
`reader-01`/`reader-02`. Nenhum segredo foi usado nessa execução.
Relatório capturado às 13:21:48 UTC; taxa sintética observada ~18 mensagens/s
durante ~1,1 s. **Não é taxa real de leitura RFID nem teste de carga do provedor.**

No Ubuntu/WSL, Paho puro Python já instalado foi disponibilizado por PYTHONPATH
para evitar alterar pacotes do sistema; `python3-venv` não estava instalado:

```bash
cd /mnt/c/Users/crowp/dev/rfid-hospital-mvp
PYTHONPATH="$PWD/.venv/Lib/site-packages" python3 -m unittest discover -s tests -v
bash -n tests/reader-connectivity/mqtt/smoke-test.sh
```

O Compose funcionou pelo Docker Desktop/CLI Windows. A tentativa de smoke na
distribuição Ubuntu retornou Docker WSL integration desativada. Habilitar essa
integração ou executar em Ubuntu com Docker instalado para validar o wrapper
shell completo; não é dependência de laboratório.

## Matriz dos critérios de aceitação

| Critério | Estado | Evidência/ação |
|---|---|---|
| Provedor escolhido e comparação objetiva | validado | ADR 0002, fontes oficiais de 2026-09-05 |
| Um ingestor e um simulador nos dois modos | validado | Factory compartilhada, suíte e Mosquitto |
| Mesmo tópico/payload, QoS 1 e retain falso | validado | Integração de 42 mensagens e fixtures |
| Campos inválidos preservados e classificados | validado | Integração e testes de parsing |
| TLS e hostname seguros no código | validado | Contexto SSL e 3 handshakes locais |
| Ausência de segredos nos logs e relatórios | validado | Redaction, testes de exceções e inspeção |
| Ingestor + dois simuladores no HiveMQ | implementado, mas aguardando teste externo | Criar cluster e executar roteiro |
| Rejeição real de senha inválida/ACL | implementado, mas aguardando teste externo | `verification --security` após controles positivos |
| Três credenciais e ACLs provisionadas | pendente | Ação no painel HiveMQ |
| Comunicação entre redes diferentes | pendente | Comandos do roteiro, registrar redes efetivas |
| Dois leitores reais e firmware TLS | pendente | Visita; associar evidências às ISS-029/ISS-030 |
| Smoke shell integral Ubuntu | pendente | Habilitar Docker na distribuição de desenvolvimento |

## Pendências separadas

Verificações finais: `git diff --check` e `git diff --cached --check` sem erros;
`compileall`, links relativos e `docker compose -f deploy/compose.yaml config --quiet` aprovados.
Os 25 arquivos preparados foram inspecionados e verificados por padrões de
segredos e exemplos de ambiente. A única ocorrência inicial foi a URL inválida
deliberadamente sintética de um teste, revisada e excluída do alerta. Nenhum
segredo real identificado. Gitleaks não estava disponível e não foi instalado.
O broker Compose temporário foi encerrado após os testes.

**HiveMQ com simuladores:** nenhum teste externo executado. Criar o cluster,
três credenciais/permissões e preencher os perfis; executar a validação positiva
e os probes. A integração de software poderá ser declarada funcional depois
dessas evidências, sem esperar hardware.

**Laboratório:** confirmar TLS, validação de certificado/hostname, 8883,
usuário/senha e Client ID configurável do EZ700; um e dois leitores simultâneos;
taxa real e duas redes quando disponíveis. Não existe ponte nesta entrega.

**Estado da issue:** aberta, não concluída. Nenhum push, PR, comentário remoto
ou fechamento autorizado nesta entrega. Ver [guia operacional](../../implementations/iss-001-mqtt-ingestion.md)
e [roteiro de campo](iss001-managed-validation.md).
