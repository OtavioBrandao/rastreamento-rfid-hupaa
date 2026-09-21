# Experimento — ingestão MQTT nas redes locais

## Objetivo

Validar que o notebook recebe e persiste eventos MQTT de um ou mais leitores EZ700 quando todos estão na mesma rede Wi-Fi.

## Hipótese

Se a rede permitir comunicação direta entre clientes e acesso TCP à porta do broker, o EZ700 publicará eventos no Mosquitto e o receptor gravará uma linha JSON completa para cada mensagem.

## Ambiente

- Notebook Ubuntu 24.04 com Mosquitto e receptor Python.
- Um ou mais leitores Identix EZ700.
- Hotspot de celular em 2,4 GHz ou Wi-Fi institucional.
- Broker no IP local do notebook e porta configurada, normalmente 1883.

## Pré-validação sem leitor

1. Iniciar o Mosquitto e o receptor.
2. Publicar eventos com `python -m rfid_ingestion.simulator`.
3. Confirmar as linhas em `data/raw_events.jsonl`.
4. Repetir com identificadores e tópicos diferentes.

## Teste 1 — hotspot do celular

1. Preferir a banda de 2,4 GHz.
2. Conectar celular, notebook e EZ700 à mesma rede.
3. Confirmar que notebook e leitor receberam IP.
4. Usar o IP do notebook como endereço do broker no EZ700.
5. Verificar se o celular permite comunicação entre clientes; dados móveis não são necessários.
6. Publicar por MQTT e confirmar o JSONL.
7. Medir estabilidade, alcance e conexão simultânea de mais de um leitor.

## Teste 2 — Wi-Fi institucional

1. Verificar se a autenticação e eventual portal de login são compatíveis com o EZ700.
2. Confirmar se há isolamento entre clientes.
3. Verificar firewall e bloqueio da porta MQTT.
4. Confirmar que o notebook pode receber conexões.
5. Registrar se o IP do notebook muda após reconexão.
6. Identificar configurações que dependem de apoio da TI.
7. Publicar por MQTT e confirmar o JSONL.

## Evidências

- Data, rede utilizada e IP local do notebook.
- Identificação dos leitores e tópicos observados, sem credenciais.
- Eventos JSONL sanitizados.
- Resultado de comunicação entre clientes e acesso à porta MQTT.
- Comportamento após queda e retorno da rede.
- Indicação de eventos armazenados ou perdidos durante desconexão.
- Resultado com publicações simultâneas de leitores diferentes.

## Critérios de aceitação

- Broker acessível na rede local sem exposição à internet.
- Leitor e notebook conseguem se comunicar.
- Mensagens válidas e inválidas não derrubam o receptor.
- Cada mensagem gera uma nova linha com metadados de recepção.
- Mais de um leitor pode publicar e ser distinguido pelo tópico e pelo payload.
- O receptor encerra de forma limpa e continua funcional após reconexão.

## Resultados

**Pendente — preencher após os testes físicos com o EZ700.**

## Conclusão

**Pendente — definir após comparar hotspot de celular e Wi-Fi institucional.**
