# ISS-001 — roteiro compacto de laboratório e redes distintas

**Estado: software validado com simuladores no HiveMQ Cloud; validação física de campo pendente.**
Historicamente, na formulação inicial desta entrega o cluster em nuvem ainda não havia sido provisionado. Em 05/09/2026, o cluster HiveMQ Cloud Serverless foi provisionado e a integração de software foi validada com sucesso utilizando simuladores sintéticos, cobrindo transporte criptografado via TLS (porta 8883), TLS + autenticação por usuário/senha e ACLs por tópico em redes distintas.

A validação física com hardware Identix EZ700 na infraestrutura de rede corporativa do HUPAA/UFAL permanece pendente de visita presencial (a ser vinculada futuramente às ISS-029/ISS-030). A evolução do software (normalização, persistência, resiliência e modelagem) não é bloqueada por essa validação de campo.

## Preparar antes da visita

- Instalar dependências e executar a suíte e o smoke local do [guia](../../implementations/iss-001-mqtt-ingestion.md).
- Criar HiveMQ e os três perfis/ACLs; executar `verification --security` com simuladores.
- Levar perfis privados, notebook carregado, acesso à Internet, cabos e duas tags.
- Combinar com a TI saída TCP 8883, DNS e acesso entre as redes necessárias.
- Usar identidades lógicas `reader-01` e `reader-02`, Client IDs distintos e
  credenciais próprias. Simuladores e leitores reais não podem usar o mesmo ID simultaneamente.
- Confirmar relógio/CA do leitor sem assumir firmware ou configuração comercial.

## Sequência de uma visita

1. No leitor 1, conferir firmware e suporte a MQTT sobre TLS, **validação de
   certificado/hostname**, porta **8883**, **usuário/senha** e **Client ID configurável**.
   Registrar suportado/não suportado/não verificado para cada item. Nunca desativar
   validação de certificado para obter um resultado positivo.
2. Configurar HiveMQ, credencial individual e o tópico
   `easy/dev/hupaa/portal-01/reader-01/readings`; QoS 1, retain falso.
3. No notebook, antes de iniciar inventário do leitor, executar:

```bash
python -m rfid_ingestion.verification --env-file config/environments/.env.cloud \
  --seconds 60 --expected-reader reader-01 --network laboratorio-cabeada \
  --report data/lab-um-leitor.json
```

4. Repetir com ambos os leitores configurados, mudando no segundo credencial,
   Client ID e o tópico para `.../reader-02/readings`:

```bash
python -m rfid_ingestion.verification --env-file config/environments/.env.cloud \
  --seconds 120 --expected-reader reader-01 --expected-reader reader-02 \
  --network laboratorio-cabeada --report data/lab-dois-leitores.json
```

5. Conferir contagens por tópico, EPC, antena, timestamp e taxa de recepção do
   relatório. A taxa é mensagens recebidas / duração total da janela, não um
   benchmark de capacidade do leitor. Comparar com contagem no leitor para estimar perda.
6. Conferir os Client IDs na configuração/painel. O relatório registra apenas
   o Client ID do ingestor quando não inicia simuladores. O protocolo recebido
   não revela o Client ID de quem publicou: não inferir identidade física do tópico.
7. Se a infraestrutura permitir, repetir na configuração de duas redes abaixo.
   Se não permitir, marcar pendente por infraestrutura; isso não bloqueia software.

Os comandos validam ambiente, DNS e TLS antes de aguardar SUBACK e mensagens,
gravam JSONL novo e relatório com etapas passadas/falhas. A coleta aceita payloads
inválidos no JSONL, mas só considera leituras do contrato para o resultado positivo.
Um leitor esperado sem dados faz a entrega falhar. O relatório mantém
`physical_validation` e `different_networks` pendentes: confirmação presencial
e topologia precisam da anotação mínima abaixo; o script não consegue prová-las.

## Comandos exatos em duas redes

Após validar o software na mesma rede, separar o ingestor na rede A e os
publicadores na rede B (por exemplo, Internet fixa e dados móveis disponíveis).
Não é necessário expor 1883, abrir porta de entrada ou criar hotspot no notebook.
Distribuir somente a credencial individual necessária a cada máquina.

**Rede A, ingestor:**

```bash
source .venv/bin/activate
python -m rfid_ingestion.verification --env-file config/environments/.env.cloud \
  --seconds 180 --expected-reader reader-01 --expected-reader reader-02 \
  --network rede-A-internet-fixa --report data/iss001-duas-redes.json
```

**Rede B, simulador 1 (iniciar após “Assinatura ativa” no ingestor):**

```bash
source .venv/bin/activate
set -a; source config/environments/.env.cloud.reader-01; set +a
python -m rfid_ingestion.simulator --reader-id reader-01 \
  --antenna 1 --count 100 --interval 0.5
```

**Rede B, simulador 2 em outro terminal ao mesmo tempo:**

```bash
source .venv/bin/activate
set -a; source config/environments/.env.cloud.reader-02; set +a
python -m rfid_ingestion.simulator --reader-id reader-02 \
  --antenna 2 --count 100 --interval 0.5
```

Para leitores reais, usar a configuração do equipamento e acionar inventário
durante a mesma janela, sem executar os simuladores. Não registrar esses
resultados como físicos quando só houve processos Python.

## Anotação mínima para acompanhar o relatório

| Campo | Preencher na visita |
|---|---|
| Data/hora e relatório | Pendente |
| Origem | Simuladores / leitores reais (selecionar o efetivo) |
| Redes A/B e evidência da separação | Pendente; rótulos, sem senhas de Wi-Fi |
| Firmware e leitor lógico | Pendente |
| Client IDs vistos na configuração/painel | Pendente; sem credenciais |
| TLS / certificado e hostname / 8883 / usuário-senha / Client ID | Cada item: suportado, não suportado ou não verificado |
| Um leitor / dois simultâneos / JSONL / taxa | Referenciar relatório e resultado |
| Revisão das ACLs e negativa de senha inválida | Referenciar relatório de probes |

As evidências compartilhadas ficam em `docs/experiments/mqtt/` após revisão;
arquivos brutos ficam em `data/`, ignorados. Não copiar `config/environments/.env`, senhas, tokens,
chaves privadas ou prints de credenciais. Registrar falhas também, sem traceback
que possa conter valores privados.

## Risco de firmware e alternativa futura

Pendente verificar diretamente no EZ700 **MQTT sobre TLS, validação de
certificado, porta 8883, usuário e senha e Client ID configurável**.
A validação física anterior de MQTT em 1883 não comprova nenhum desses itens.
Se TLS não for suportado, uma alternativa futura a avaliar é:

`EZ700 → broker ou gateway local → HiveMQ Cloud com TLS → ingestor`.

**Nenhuma ponte foi implementada nesta issue.** Não alterar o núcleo do ingestor
para acomodar firmware: eventual adaptação pertence à borda/gateway e a outra issue.
