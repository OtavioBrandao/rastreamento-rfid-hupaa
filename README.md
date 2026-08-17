# RFID Hospital MVP

MVP para rastreabilidade aproximada, por zonas, de equipamentos hospitalares do HUPAA/UFAL usando RFID UHF passivo. A posição de um ativo será inferida a partir de sua última passagem detectada, e não por posicionamento contínuo em ambiente interno.

## Fase atual

O projeto está na etapa inicial de validação de infraestrutura local. O primeiro experimento verifica se um notebook com Ubuntu 24.04 pode criar um hotspot Wi-Fi isolado, hospedar uma página local e ser acessado por um telefone ou outro dispositivo sem internet e sem a rede institucional.

Consulte o [roteiro do experimento de hotspot](tests/hotspot/README.md) e o [registro do experimento](docs/experiments/hotspot-validation.md).

Integração com o leitor Identix EZ700, arquitetura do servidor, escolha entre MQTT e HTTP, banco de dados, lógica de portal e dashboard estão fora do escopo deste commit inicial. Esses itens dependem de validações físicas posteriores do hardware e de seus protocolos e payloads reais.
