# Sistema visual do dashboard RFID

Este protótipo usa dados demonstrativos. A cor indica significado, sempre acompanhada de texto ou forma. O mapa indica **zona da última detecção**, nunca posição exata ou localização em tempo real.

## Tokens

Os valores são centralizados em `src/styles/main.css` como variáveis CSS.

| Uso | Token | Cor |
| --- | --- | --- |
| Canvas / superfície | `--canvas` / `--surface` | `#f5f7f6` / `#ffffff` |
| Navegação | `--slate` | `#172b32` |
| Ação e foco | `--teal` | `#006f73` |
| Disponível | `--available` | `#168461` |
| Atenção | `--attention` | `#ad6b08` |
| Offline | `--offline` | `#71818a` |
| Fora de serviço | `--critical` | `#b83d3d` |
| Antena RFID | `--antenna` | `#df3f45` |
| Leitor RFID | `--reader` | `#365fc4` |

O zoneamento do HUPAA é uma camada de contexto independente dos estados. Serviço `#f7b6ad`, administrativo `#b89891`, circulação vertical `#a9d9ae`, circulação horizontal `#c1a1c8`, institucional `#a8d9ec` e permanência/atendimento `#f3df99`. A legenda separa zonas de infraestrutura e equipamentos.

Fonte: pilha de sistema (`Segoe UI`, Arial). Título entre 30 e 42 px; subtítulos 20–24 px; corpo 14–16 px; rótulos de categoria 11 px, caixa alta e espaçamento de letras. Espaçamento base de 4 px, com passos de 8, 12, 16, 24 e 32 px. Raio de 10–16 px; painéis têm borda fina. Só o painel de detalhe usa elevação discreta. Ícones de interface são SVG lineares de um único conjunto local, sem dependência externa.

As formas no mapa usam as referências visuais como esquema e coordenadas percentuais. São ilustrativas; a equipe deve calibrar zonas, antenas e portais após a validação física.
