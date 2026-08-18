# RFID Hospital MVP

MVP para rastreabilidade aproximada, por zonas, de equipamentos hospitalares do HUPAA/UFAL usando RFID UHF passivo. A posição de um ativo será inferida a partir de sua última passagem detectada, e não por posicionamento contínuo em ambiente interno.

## Fase atual

A Prova de Conceito foi concluída. A primeira camada do MVP recebe eventos enviados por múltiplos leitores Identix EZ700 por MQTT e os persiste localmente no notebook em JSON Lines. O notebook não cria a rede Wi-Fi: ele funciona como broker Mosquitto e receptor, conectado à mesma rede dos leitores.

```text
EZ700 -> Wi-Fi local -> Mosquitto no notebook -> receptor Python -> data/raw_events.jsonl
```

O formato e a configuração reais do EZ700 ainda dependem de validação física. A fixture atual reproduz o JSON documentado pela Identix sem rejeitar campos adicionais.

## Execução rápida

No Ubuntu 24.04, a partir da raiz do repositório:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
docker compose up -d
python -m rfid_ingestion
```

Em outro terminal, com o mesmo ambiente virtual ativo:

```bash
python -m rfid_ingestion.simulator --reader-id EZ700-SIM-01 --count 3 --interval 1
```

Os eventos são anexados a `data/raw_events.jsonl`. Consulte o [guia completo de ingestão MQTT](docs/mqtt-ingestion.md) e o [roteiro dos testes de rede](docs/experiments/mqtt-network-validation.md).

## Escopo

Esta etapa contém broker local de desenvolvimento, receptor, simulador, persistência JSONL e testes. Dashboard, frontend, CRUD, banco de dados externo, nuvem, lógica definitiva de portal e implantação de produção continuam fora do escopo.
