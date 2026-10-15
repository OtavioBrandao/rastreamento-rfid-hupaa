# Ordenação estável de equipamentos nas tabelas

## Problema e importância para o MVP

O inventário priorizava a leitura mais recente e os detectados usavam a contagem
de leituras como desempate. A cada atualização os equipamentos trocavam de
posição, dificultando o acompanhamento durante a demonstração. A aba de ativos
nas salas não aplicava a mesma prioridade da zona selecionada.

## Solução

O inventário ordena no PostgreSQL antes de paginar. As tabelas do mapa e de
detectados seguem os mesmos grupos, avaliados com um relógio por ordenação:

1. Em trânsito com leitura nos últimos 30 segundos.
2. Em trânsito sem leitura nessa janela.
3. Demais equipamentos com leitura nos últimos 30 segundos.
4. Atenção necessária.
5. Sem detecção confirmada.
6. Fora de serviço e demais estados.

Dentro de cada grupo, nome em ordem alfabética/natural e ID como desempate:
`Bomba 1`, `Bomba 2`, `Bomba 10`. Horário e volume de leituras não desempatam.
Uma linha muda de grupo se seu estado mudar ou a presença expirar. Não fica
congelada em um grupo antigo. O rótulo “Em trânsito” corresponde ao contrato
`disponivel`; leitura recente não confirma zona nem altera o status do domínio.

`api.service_busca_ativos._nome_natural` divide o nome em segmentos numéricos e
textuais. A chave SQL ignora caixa e acentos portugueses e compara os segmentos
numéricos sem conversão a inteiro. O frontend usa `Intl.Collator('pt-BR')` com
comparação numérica e sensibilidade básica. Sinais e caracteres fora do alfabeto
português podem ter colação diferente entre PostgreSQL e o navegador; os grupos
e os exemplos de patrimônio permanecem determinísticos em cada consulta.

## Validação

Regressões verificam prioridade global entre páginas, tag desvinculada, expiração,
leitura recente sem zona, trânsito antes de atenção, números naturais e estabilidade
após novas leituras. Frontend verifica também nomes iguais com IDs diferentes.
O registro consolidado está em [validações da versão](../operations/validation.md).
