# Correção da imagem do ingestor: pacotes de inferência

## Problema e importância para o MVP

O `Dockerfile` copiava `rfid_ingestion`, mas deixava de fora os pacotes irmãos
`rfid_inference`, `rfid_movement` e `rfid_location`. O ingestor importa
`rfid_inference.debounce` na inicialização; por isso a imagem construída não
conseguia iniciar o serviço, apesar de o código funcionar no host.

## Resolução

O `Dockerfile` agora copia os três pacotes para `/app`, junto do ingestor.
Assim o mesmo pipeline de ingestão, passagem, movimentação e localização está
disponível dentro da imagem. Nenhum contrato MQTT ou formato do EZ700 foi alterado.

## Validação

O launcher usa `docker compose up --build` para reconstruir a imagem antes do
teste. Para verificar manualmente: `docker compose --env-file .env.local
--profile local build ingestor-local` e depois `docker compose --env-file
.env.local --profile local run --rm --no-deps ingestor-local python -c
"import rfid_inference.debounce, rfid_movement, rfid_location"`.
