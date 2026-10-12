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
  com os equipamentos daquela zona. Fechar o cluster (×, Esc, clique fora ou
  **Fechar zona e voltar às abas**) restaura as abas no estado anterior.
- Se a topologia deixar de validar a zona selecionada, a seleção é desfeita.

### Tempo real

`useLiveQuery` (ativos, topologia e leituras recentes) e o polling de
`/api/laboratorio/leituras` que gera o pulso das antenas seguem ativos; o
cluster e a tabela da zona recalculam a cada atualização.

### Script `scripts/dev.py`

```bash
python scripts/dev.py                       # ingestor + API + frontend com .env.cloud
python scripts/dev.py --env-file .env.local
python scripts/dev.py --sem-ingestor        # só API + frontend
python scripts/dev.py --api-port 8010       # se a 8000 estiver ocupada
```

- Usa o Python da `.venv` quando existir; executa `npm ci` se faltar
  `frontend/node_modules`.
- Mostra a saída dos três processos com prefixos `[ingestor]`, `[api]` e
  `[front]`; `Ctrl+C` encerra a árvore de processos inteira (Windows e Ubuntu).
- O arquivo de ambiente é carregado pelos próprios processos; o script não lê
  nem exibe credenciais.
- `--api-port` é repassado ao proxy do Vite pela variável `RFID_API_URL`
  (`frontend/vite.config.ts`, padrão `http://127.0.0.1:8000`).

## Validação

- `npm test` (24 testes, incluindo cluster, tabela contextual e restauração das
  abas) e `npm run build`.
- Verificação manual com API real nas larguras desktop e 375 px.
