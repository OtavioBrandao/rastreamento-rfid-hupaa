# Sistema visual do dashboard RFID

Este protótipo usa dados demonstrativos. A cor indica significado, sempre acompanhada de texto ou forma. O mapa indica **zona da última detecção**, nunca posição exata ou localização em tempo real.

## Tokens

Os valores são centralizados em `src/styles/main.css` como variáveis CSS.

| Uso | Token | Cor |
| --- | --- | --- |
| Canvas / superfície | `--canvas` / `--surface` | `#f3f7fb` / `#ffffff` |
| Navegação | `--slate` | `#102a42` |
| Ação e foco | `--blue` | `#006d9f` |
| Azul UFAL de referência | `--ufal-blue` | `#0095da` |
| Disponível | `--available` | `#156f9e` |
| Atenção | `--attention` | `#ad6b08` |
| Offline | `--offline` | `#71818a` |
| Fora de serviço | `--critical` | `#b83d3d` |
| Contorno/ícone do total | `--kpi-total` | `#102a42` |
| Contorno/ícone de disponíveis | `--kpi-available` | `#188038` |
| Contorno/ícone de atenção | `--kpi-attention` | `#a45b00` |
| Contorno/ícone de fora de serviço | `--kpi-critical` | `#c62828` |
| Contorno/ícone de nunca detectados | `--kpi-offline` | `#526675` |
| Antena RFID | `--antenna` | `#df3f45` |
| Leitor RFID | `--reader` | `#365fc4` |

O azul da identidade visual da UFAL segue o [manual institucional](https://ufal.br/ufal/comunicacao/identidade-visual/manual-de-identidade-visual.pdf), que especifica `#0095DA` para web. O tom de ação é mais escuro para manter contraste.

Os cinco indicadores de “Situação dos equipamentos” mantêm fundo branco e usam o respectivo token apenas no contorno e no selo do ícone. O total usa azul-marinho e contorno mais fino; os demais usam verde, âmbar, vermelho e grafite de maior presença. Cada indicador combina rótulo, número e ícone. O contraste calculado do branco sobre os selos varia de 5,02:1 a 14,67:1; o rótulo `#435461` sobre branco atinge 7,84:1 (WCAG AA).

As **três zonas principais** da planta são provisórias: Zona 1 (ala superior esquerda), Zona 2 (ala superior direita) e Zona 3 (bloco inferior com ligação central). As cores do desenho mostram apenas o contexto arquitetônico: serviço `#F31217`, administrativo `#633937`, circulação vertical `#00E820`, circulação horizontal `#67008F`, institucional `#12BCE8` e permanência/atendimento `#FFCA08`. Elas não representam as três zonas principais, status de equipamentos ou localização decidida para portais.

Fonte: pilha de sistema (`Segoe UI`, Arial). Título entre 30 e 42 px; subtítulos 20–24 px; corpo 14–16 px; rótulos de categoria 11 px, caixa alta e espaçamento de letras. Espaçamento base de 4 px, com passos de 8, 12, 16, 24 e 32 px. Raio de 10–16 px; painéis têm borda fina. Só o painel de detalhe usa elevação discreta. Ícones de interface são SVG lineares de um único conjunto local, sem dependência externa.

O contorno da planta segue o traçado fornecido pela equipe, ainda como esquema sem escala de CAD. A posição dos portais hospitalares não está definida. As posições de equipamentos são fictícias e ficam ocultas por padrão para deixar a planta legível.
