# Validação de hotspot local no Ubuntu

## 1. Propósito

Este experimento verifica uma única premissa de infraestrutura: um notebook Ubuntu 24.04 consegue criar uma rede Wi-Fi isolada, hospedar uma página HTTP local e ser acessado por outro dispositivo sem internet e sem depender da rede institucional. Ele não valida o leitor Identix EZ700 e não representa o backend nem a arquitetura final do MVP.

Os scripts alteram a rede **somente quando `start-hotspot.sh` ou `stop-hotspot.sh` é executado no Ubuntu**. `check-capabilities.sh`, `hotspot-status.sh` e `collect-results.sh` fazem apenas consultas. Nenhum script instala pacotes.

## 2. Arquitetura esperada

```text
Telefone ou outro cliente
          |
          | Wi-Fi: RFID-MVP-TEST (sem internet)
          v
Notebook Ubuntu 24.04
  hotspot: 10.42.0.1/24
  servidor HTTP: 0.0.0.0:8000
          |
          +--> http://10.42.0.1:8000
```

O notebook cria o hotspot e executa o servidor. O telefone entra nessa rede e abre `http://10.42.0.1:8000`.

## 3. Pré-requisitos

- Ubuntu 24.04 executado diretamente no notebook, não no Windows ou WSL.
- NetworkManager ativo e ferramenta `nmcli` disponível.
- Ferramentas `ip` e `python3` disponíveis.
- Interface Wi-Fi com suporte a modo AP/hotspot.
- Opcional: `iw`, para uma segunda verificação da capacidade do driver.
- Telefone ou outro cliente Wi-Fi com navegador.
- Acesso local para autorizar alterações do NetworkManager, se solicitado pelo Ubuntu.

O acesso à internet não é necessário durante o teste. Se um pré-requisito estiver ausente, os pacotes podem ser instalados **manualmente**, conforme a política da máquina. Por exemplo:

```bash
sudo apt update
sudo apt install network-manager iproute2 python3 iw
```

Não execute instalações sem antes revisar e autorizar os pacotes. Algumas versões/configurações do NetworkManager também podem exigir `dnsmasq-base`; consulte a seção de solução de problemas.

Após clonar o repositório no Ubuntu, entre no diretório e, se necessário, restaure a permissão de execução:

```bash
cd rfid-hospital-mvp/tests/hotspot
chmod +x ./*.sh
```

## 4. Identificar a interface Wi-Fi

Não presuma que ela se chama `wlan0`. Liste as interfaces reconhecidas pelo NetworkManager:

```bash
nmcli -f DEVICE,TYPE,STATE device status
```

Procure uma linha cujo tipo seja `wifi`, por exemplo `wlp2s0`. Quando houver uma única interface, os scripts podem selecioná-la automaticamente. Com duas ou mais, informe o nome explicitamente.

## 5. Verificar capacidades sem alterar a rede

Com uma única interface Wi-Fi:

```bash
./check-capabilities.sh
```

Com mais de uma interface:

```bash
./check-capabilities.sh NOME_DA_INTERFACE
```

O comando verifica Linux, NetworkManager, ferramentas obrigatórias e suporte a AP. Mensagens `PASSOU`, `AVISO` e `FALHOU` distinguem o resultado; uma falha obrigatória produz código de saída diferente de zero. Nenhum pacote é instalado e nenhuma conexão é ativada ou alterada.

## 6. Iniciar o hotspot

Leia o aviso: uma placa Wi-Fi geralmente deixa a conexão atual para assumir o modo AP. Em uma máquina acessada remotamente por Wi-Fi, faça o teste somente com acesso local ao notebook.

```bash
./start-hotspot.sh --interface NOME_DA_INTERFACE
```

Na primeira execução, o script solicita uma senha WPA em um prompt sem eco. Escolha uma senha de 8 a 63 caracteres ASCII imprimíveis, ou uma chave de 64 dígitos hexadecimais. A senha não aparece no terminal nem é escrita no repositório.

Os padrões são:

- perfil `rfid-mvp-hotspot`;
- SSID `RFID-MVP-TEST`;
- banda 2,4 GHz (`bg`);
- host `10.42.0.1/24`;
- IPv4 compartilhado;
- IPv6 e autoconexão desativados.

Consulte todas as opções:

```bash
./start-hotspot.sh --help
```

Exemplo sem credencial para substituir SSID, nome do perfil e rede:

```bash
./start-hotspot.sh \
  --interface NOME_DA_INTERFACE \
  --ssid NOME_DO_SSID \
  --connection NOME_DO_PERFIL \
  --host-cidr 10.42.0.1/24
```

Se o perfil dedicado já existir, o script verifica que ele é um AP com IPv4 compartilhado e o ativa sem alterá-lo. Uma opção explícita incompatível falha de forma segura. Para mudar a configuração, desative e exclua **manualmente apenas o perfil dedicado**, depois recrie-o:

```bash
nmcli connection down id rfid-mvp-hotspot
nmcli connection delete id rfid-mvp-hotspot
./start-hotspot.sh --interface NOME_DA_INTERFACE
```

Revise o nome antes de excluir. O script nunca exclui um perfil existente.

## 7. Iniciar o servidor HTTP

Abra outro terminal no mesmo diretório:

```bash
./serve-test-page.sh
```

O servidor usa `0.0.0.0:8000` e mostra a URL esperada. Para escolher outra porta:

```bash
./serve-test-page.sh 8080
```

Este servidor Python é somente uma sonda de conectividade. Não é adequado como backend do MVP.

## 8. Conectar o telefone e validar

1. No telefone, abra as configurações de Wi-Fi.
2. Entre no SSID `RFID-MVP-TEST` (ou no SSID escolhido) com a senha informada no notebook.
3. O sistema pode avisar que a rede não possui internet; permaneça conectado a ela.
4. Desative temporariamente a troca automática para dados móveis se o navegador insistir em sair da rede local.
5. Abra `http://10.42.0.1:8000`.
6. Confirme o título, a mensagem de conexão local e o horário gerado no próprio cliente.

Não digite nem registre a senha em issues, capturas, arquivos de resultado ou comandos destinados ao histórico.

## 9. Inspecionar o estado e os clientes

```bash
./hotspot-status.sh
```

O relatório mostra existência e ativação do perfil, interface, IPv4 do host, URL esperada e IPs de clientes conhecidos. Endereços MAC e segredos salvos não são consultados nem exibidos. A tabela de vizinhos pode permanecer vazia até o telefone trocar tráfego com o notebook; tente abrir a página e execute o comando novamente.

Para perfil ou porta não padrão:

```bash
./hotspot-status.sh --connection NOME_DO_PERFIL --port 8080
```

## 10. Coletar resultados sanitizados

Depois da tentativa, informe o resultado observado:

```bash
./collect-results.sh --status sucesso
```

Ou:

```bash
./collect-results.sh --status falha
```

O script gera `results/hotspot-validation-AAAAMMDD-HHMMSS.md` com data, versões, capacidade AP, perfil, interface, IPv4 e IPs dos clientes. Ele omite hostname, endereços MAC e credenciais. Arquivos de execução em `results/` são ignorados pelo Git, exceto `.gitkeep`.

**Revise o conteúdo antes de compartilhar ou adicionar manualmente qualquer resultado ao Git.** Não anexe saída bruta de comandos capazes de conter senhas, tokens, credenciais do GitHub ou outros identificadores.

## 11. Parar o hotspot

Interrompa primeiro o servidor HTTP com `Ctrl+C`. Depois desative o perfil dedicado:

```bash
./stop-hotspot.sh
```

Para outro perfil:

```bash
./stop-hotspot.sh NOME_DO_PERFIL
```

O comando não exclui o perfil. Se ele já estiver inativo ou não existir, termina com sucesso sem modificar outras conexões.

## 12. Solução de problemas

### A placa Wi-Fi não suporta AP

Confirme os resultados do NetworkManager e, se disponível, de `iw`. Atualize driver/firmware somente segundo a política do notebook. Se o hardware realmente não anunciar modo AP, use outro adaptador compatível ou reavalie um roteador/AP offline. Não force o experimento em hardware incompatível.

### Há várias interfaces Wi-Fi

Liste-as com `nmcli -f DEVICE,TYPE,STATE device status` e repita os comandos com a interface pretendida. Em `start-hotspot.sh`, use `--interface NOME_DA_INTERFACE`. A seleção explícita evita alterar a interface errada.

### NetworkManager está inativo

Consulte o estado:

```bash
systemctl status NetworkManager
```

Se a política local permitir, um administrador pode iniciá-lo manualmente:

```bash
sudo systemctl start NetworkManager
```

Os scripts não iniciam serviços nem instalam componentes automaticamente.

### O cliente não recebe endereço IP

- Confirme que o perfil está ativo e usa `ipv4.method shared` com `./hotspot-status.sh`.
- Desconecte e reconecte o Wi-Fi no cliente.
- Esqueça a rede no cliente apenas se puder reinserir a senha sem registrá-la.
- Consulte os logs locais do NetworkManager sem copiá-los diretamente para o repositório: `journalctl -u NetworkManager --since today`.
- Revise se o serviço de DHCP/DNS do modo compartilhado iniciou; veja também `dnsmasq-base` abaixo.

### O firewall do Ubuntu bloqueia a porta 8000

Verifique primeiro se o firewall está ativo:

```bash
sudo ufw status verbose
```

Se estiver ativo e a política do notebook permitir, abra temporariamente a porta TCP 8000 para o teste:

```bash
sudo ufw allow 8000/tcp comment 'RFID MVP teste local'
```

Após o experimento, remova a regra criada:

```bash
sudo ufw delete allow 8000/tcp
```

Confirme também que `serve-test-page.sh` continua em execução e que não há outro processo ocupando a porta.

### O hotspot derruba a conexão Wi-Fi atual

Esse comportamento é esperado quando uma única placa não mantém simultaneamente os modos cliente e AP. O experimento não precisa de internet. Faça-o com acesso físico ao notebook. Se conectividade simultânea for indispensável em testes futuros, avalie um segundo adaptador ou um AP dedicado.

### O NetworkManager informa ausência de `dnsmasq-base`

Algumas instalações/versões precisam do componente para DHCP/DNS no modo IPv4 compartilhado. Confirme a mensagem nos logs e, se permitido pela política local, instale manualmente:

```bash
sudo apt update
sudo apt install dnsmasq-base
```

Depois, tente ativar novamente o perfil. Os scripts nunca executam essa instalação.

## 13. Segurança das evidências

Nunca faça commit de senha do hotspot, tokens, credenciais do GitHub, saída de `nmcli --show-secrets`, arquivos de conexão do NetworkManager ou logs brutos sem revisão. Não use credenciais reais como exemplos. Os relatórios automáticos são deliberadamente limitados e ignorados pelo Git até revisão humana.

## 14. Critérios de aceitação

O experimento é aceito quando:

- a interface e o driver indicam capacidade suficiente para AP;
- o perfil dedicado ativa com o IPv4 planejado;
- um telefone ou outro cliente entra no hotspot e recebe IPv4;
- o cliente abre a página local sem acesso à internet;
- o status identifica o host e, após tráfego, o cliente;
- um resultado sanitizado é gerado e revisado;
- o hotspot é desativado sem remover o perfil nem modificar conexões não relacionadas.

Se algum item falhar, registre o status como `falha`, preserve somente evidências sanitizadas e trate o resultado como informação para reconsiderar a topologia — não como autorização para implementar ainda o backend ou a integração do leitor.
