# Experimento — validação de hotspot local no Ubuntu

## Objetivo

Verificar se um notebook com Ubuntu 24.04 pode criar uma rede Wi-Fi local isolada e servir uma página HTTP acessível por outro dispositivo sem internet e sem usar a rede institucional.

## Hipótese

Se a interface Wi-Fi suportar modo AP e o NetworkManager estiver operacional, um cliente conectado ao hotspot `RFID-MVP-TEST` receberá um endereço IPv4 e abrirá `http://10.42.0.1:8000` enquanto o servidor de teste estiver ativo.

## Ambiente

- Notebook com Ubuntu 24.04 e NetworkManager.
- Interface Wi-Fi com suporte a modo AP.
- Scripts em `tests/hotspot/`.
- Telefone ou outro dispositivo com Wi-Fi e navegador.
- Sem requisito de acesso à internet ou à rede do hospital.

Registrar no resultado a versão real do sistema, a versão do NetworkManager e a interface usada, sem incluir senhas, endereços MAC ou outros identificadores desnecessários.

## Procedimento

1. Executar `check-capabilities.sh` sem alterar a rede.
2. Identificar explicitamente a interface caso haja mais de uma opção.
3. Executar `start-hotspot.sh`, ler o aviso de desconexão e informar uma senha somente no prompt oculto.
4. Em outro terminal, executar `serve-test-page.sh`.
5. Conectar o dispositivo cliente ao SSID configurado.
6. Abrir `http://10.42.0.1:8000` no cliente e confirmar a página local.
7. Executar `hotspot-status.sh` e `collect-results.sh --status sucesso` se a validação funcionar, ou usar `--status falha` caso contrário.
8. Revisar o arquivo gerado antes de qualquer compartilhamento.
9. Encerrar o hotspot com `stop-hotspot.sh`.

O roteiro operacional completo está em [`tests/hotspot/README.md`](../../tests/hotspot/README.md).

## Evidências a coletar

- Data e hora do teste.
- Sistema operacional e versão do NetworkManager.
- Resultado da verificação de suporte a AP.
- Nome da conexão dedicada e interface utilizada.
- Endereço IPv4 do host.
- IPs de clientes visíveis, com endereços MAC omitidos.
- Confirmação manual de abertura da página ou descrição curta da falha.

## Critérios de aceitação

- A capacidade de AP é identificada sem alterações de rede.
- O perfil dedicado é ativado e o host recebe `10.42.0.1/24` (ou o CIDR explicitamente escolhido).
- Um cliente entra no hotspot e recebe um endereço IPv4.
- O cliente abre a página local na porta 8000 sem internet.
- O resultado sanitizado é gerado e revisável.
- O perfil é desativado sem remover ou alterar conexões não relacionadas.

## Resultados

**Pendente — preencher somente após a execução física no notebook Ubuntu.**

## Conclusão

**Pendente — decidir após revisar as evidências do experimento físico.**
