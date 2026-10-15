# Mapa / Planta: abas inferiores, cluster por zona e script de desenvolvimento

## O que é

Refatoração exclusivamente de front-end da página **Mapa / Planta** (HUPAA e
Laboratório EASY), mais um script que sobe ingestor, API e frontend em um só
terminal. Nenhuma rota, contrato de API ou regra de backend foi alterada.

## Por que importa para o MVP

- A coluna lateral direita repetia informação e espremia a planta e a tabela.
  Com ela desocupada, mapa e tabela usam a largura total da tela.
- O bloco **Leituras das antenas** duplicava a página **Leituras**, que já
  mostra o fluxo em tempo real. No mapa ficou apenas o pulso das antenas.
- O operador precisa ver rapidamente *quem* está em uma sala, sem procurar em
  listas laterais. O cluster circular responde isso com um clique.
- Para testar o sistema eram necessários três terminais (ingestor, API e
  frontend). O `scripts/dev.py` reduz isso a um comando.

## O que foi feito

### Layout

- Removidos da lateral: *Leituras das antenas*, *Zonas e portais*,
  *Ativos nas salas*, *Sem zona confirmada* e *Outras zonas*.
- Abaixo da planta há agora um componente de abas (`MapDataTabs`), com
  navegação por clique e por teclado (setas, Home, End):
  1. **Equipamentos detectados** (padrão — tabela que já existia);
  2. **Ativos nas salas**;
  3. **Zonas e portais**;
  4. **Sem zona confirmada**;
  5. **Outras zonas**.
- Os painéis ficam montados e só são ocultados, então trocar de aba não
  recarrega a tela nem interrompe as consultas ao vivo.

### Interatividade na planta

- Ao passar o mouse sobre o marcador de equipamentos de uma zona, o tooltip
  mostra **"Clique para ver os equipamentos"**. O nome acessível do marcador
  continua informando a quantidade e a zona.
- No EASY, as salas A e B inteiras são clicáveis; no HUPAA, os rótulos de zona
  e os marcadores abrem a mesma visualização.
- O clique abre um **cluster circular** (`ZoneCluster`) sobre a planta com uma
  bolinha por equipamento da zona. A distribuição em girassol é ilustrativa e
  estável entre atualizações, pois o sistema trabalha por zona de presença e
  não por coordenada.
  - **Verde:** em trânsito / detectado recentemente (status disponível ou
    leitura nos últimos 30 s).
  - **Amarelo:** atenção necessária ou desatualizado.
- Clicar em uma bolinha abre o painel de detalhes do equipamento (histórico,
  EPC, metadados e status).
- Enquanto a zona está selecionada, as abas são substituídas por uma tabela só
  com os equipamentos daquela zona, ordenada por prioridade: primeiro os em
  trânsito, depois os que pedem atenção e, por último, os marcados com
  "localização pode estar desatualizada".
- Fechar o cluster (×, Esc, clique fora ou
  **Fechar zona e voltar às abas**) restaura as abas no estado anterior.
- Se a topologia deixar de validar a zona selecionada, a seleção é desfeita.

### Tempo real

`useLiveQuery` (ativos, topologia e leituras recentes) e o polling de
`/api/laboratorio/leituras` que gera o pulso das antenas seguem ativos; o
cluster e a tabela da zona recalculam a cada atualização.

### Script `scripts/dev.py`

Antes eram necessários vários terminais: o launcher de laboratório
(`python -m tools.lab_launcher`), a API e o frontend. Agora:

```bash
python scripts/dev.py                         # menu 1-4
python scripts/dev.py --teste 4               # escolhe direto
python scripts/dev.py --sem-teste             # só API e frontend, banco externo
python scripts/dev.py --api-port 8020 --front-port 5180   # se as portas estiverem ocupadas
```

| Opção | O que acontece |
| --- | --- |
| 1 | Local com simulador visual (dados sintéticos) |
| 2 | Local com leitor físico |
| 3 | Broker e banco externos com leitor físico |
| 4 | Broker e banco externos com simulador visual (dados sintéticos) |

1. O script mostra o mesmo menu do launcher de laboratório.
2. Sobe a API (porta padrão **8010**) e o frontend Vite (porta 5173) em segundo
   plano, espera os dois responderem e abre o navegador. A API usa o mesmo
   banco do cenário: o PostgreSQL local (montado a partir do `config/environments/.env.local`,
   como faz o launcher) nas opções 1 e 2, e o banco externo do `config/environments/.env.cloud`
   nas opções 3 e 4 (e em `--sem-teste`).
3. Entrega o terminal ao `tools.lab_launcher start --env ... --source ...`,
   que segue com as perguntas dele (transporte, tags físicas), sobe Docker,
   ingestor e migrations, abre os três terminais de observação (MQTT,
   Ingestor e Banco) e, nas opções 1 e 4, abre o
   [simulador visual](simulador-visual-laboratorio.md) para mover os itens
   pela planta. Sem o Flet (`requirements/lab.txt`), o script avisa antes de
   subir qualquer coisa.
4. `Ctrl+C` encerra o launcher (que derruba os contêineres) e depois a API e
   o frontend, inclusive os processos filhos do `npm` (Windows e Ubuntu).

Com o launcher em primeiro plano, a saída da API e do frontend fica em
`data/dev/api.log` e `data/dev/front.log` (ignorados pelo Git) para não se
misturar às perguntas. Com `--sem-teste` ela aparece no próprio terminal. Nenhuma
credencial é exibida nem passada na linha de comando.

`--api-port` é repassado ao proxy do Vite pela variável `RFID_API_URL`
(`frontend/vite.config.ts`, padrão `http://127.0.0.1:8010`). A porta padrão
passou de 8000 para 8010 porque a 8000 costuma estar ocupada por outros
projetos locais; para subir a API manualmente, use `--port 8010`.

### Janela "Banco" do launcher reexibia o histórico

O observador do banco (`tools/lab_launcher/watch.py`) começava do `id` 0 e lia
100 leituras a cada 2 s. Com mais de 130 mil leituras guardadas (a maioria do
ensaio de 07/10), a janela passava dezenas de minutos mostrando leituras antigas
como se estivessem chegando naquele momento. Agora ele parte da última leitura,
da última movimentação e das passagens já existentes, e mostra só o que chegar
depois de aberto.

### Simulador reaproveita equipamentos pelo nome

Cada "Gerar itens no mapa" sorteava EPCs novos, e o cadastro criava um
equipamento novo para cada um. Assim, o mesmo nome (ex.: "Bomba X") virava vários
equipamentos. Agora `epcs_por_nome` (`tools/lab_launcher/seed.py`) procura o
equipamento sintético com o mesmo nome (sem diferenciar maiúsculas/espaços) e o
simulador reutiliza a tag dele, mantendo histórico e última zona. Se houver
homônimos, vale o ativo detectado por último; um equipamento inativo é
reativado. Só nomes novos recebem EPC sorteado. Duplicatas criadas antes desta
correção continuam no banco.

## Validação

- `npm test` (24 testes, incluindo cluster, tabela contextual e restauração das
  abas) e `npm run build`.
- Verificação manual com API real nas larguras desktop e 375 px.
- `scripts/dev.py --sem-teste` validado no Windows (API, proxy e encerramento).
