# ISS-023 — Vínculos da planta com zonas e portais

## Issue e importância para o MVP

A issue #25 permite localizar ativos por zonas em uma planta 2D. A maior parte
da interface já existia, mas faltava identificar os portais cadastrados no mapa
e demonstrar a correspondência entre o ID da zona e a região visual.

## Implementação

- `frontend/src/config/mapaConfig.ts` reúne regiões e posições de portais do
  EASY/HUPAA. As coordenadas são percentuais e pertencem ao esquema, nunca ao
  equipamento. A representação dos ativos continua agregada por zona.
- A árvore de `/localizacoes/arvore` resolve `referencia_planta` em um único
  `zone_id` ativo. Referências ausentes ou duplicadas não são posicionadas.
  Um ativo só pertence à região quando ID **e** referência correspondem.
- `/portais` é percorrido até a última página. No EASY, o nome estável
  `Portal de teste RFID` resolve o ID real da instalação; ambos os lados são
  conferidos pelos IDs das zonas. Portais ausentes, ambíguos, inativos ou com
  lados incompatíveis não recebem posição. Pode-se configurar `portalId`
  diretamente em vez de `portalName`.
- O marcador identifica o portal e seus lados A/B. A lista textual explica a
  passagem, oferece contagem e seleção de zonas, inclusive vazias, e permite
  consultar os ativos sem depender do desenho.
- As listas preservam status e aviso de localização desatualizada, inclusive
  para ativos fora da planta. Nunca detectados permanecem separados.
- O proxy do Vite inclui `/portais`. A atualização automática da ISS-033 cobre
  os ativos e a topologia; falha na topologia remove posições não verificáveis
  e mantém a consulta textual, com recuperação automática.

## Configuração e limites

Para substituir regiões, edite os metadados e associe cada referência a uma
única zona cadastrada. Para um portal, informe `portalId` ou `portalName`,
`zoneA`, `zoneB`, `x` e `y`; os lados precisam corresponder à API. Isso não
modifica o motor de rastreamento nem o protocolo do leitor.

O EASY reutiliza o esquema existente, **sem escala ou medições físicas
validadas nesta entrega**. O HUPAA mantém `hospitalPortals` vazio até confirmar
planta autorizada e posições reais. O aceite de campo e a revisão pela dupla
continuam separados da validação sintética do software. Não foi feito ensaio
físico com EZ700 nesta implementação.

## Validação — 05/10/2026

- Frontend: 21 testes aprovados e build TypeScript/Vite aprovado, em conjunto
  com a ISS-033. Cobrem IDs reais diferentes do seed, referências ambíguas,
  inatividade, lados incompatíveis, configuração substituível, paginação de
  portais, mudança Sala A → Sala B, contagem, seleção e fallback após falha.
- Navegador: dashboard e EASY com API sintética local; marcador de portal
  #907, atualização das zonas, detalhes e apresentação em desktop e viewport
  móvel de 390 × 844. Não houve transbordamento horizontal da página móvel.
  [Captura móvel do EASY](assets/iss-023-mapa-mobile.png).
- Regressão Python: 356 testes e 90 subtestes aprovados; 532 testes pulados por
  ausência dos serviços/configurações de integração locais. Não equivalem a
  uma validação integrada com banco, MQTT ou leitor físico.

```bash
npm --prefix frontend test
npm --prefix frontend run build
python -m pytest -q tests --basetemp .tmp_pytest_sprint3_final
```
