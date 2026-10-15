# Material de apoio — Marco 2

**Entrega prevista: 16/10/2026.** Este material organiza os insumos do repositório
para redigir o documento acadêmico de desenvolvimento e versão funcional. Não
substitui a redação final nem preenche resultados de medições que não foram feitas.
A versão candidata é `v0.1.0-rc.1`, identificada também na API e no pacote frontend.

## Problema, objetivo e recorte

O Rastreamento RFID HUPAA busca apoiar a localização de equipamentos móveis no
Hospital Universitário Professor Alberto Antunes, usando passagens RFID para
estimar a última zona conhecida. A entrega é um MVP demonstrável de software e
integração experimental, com cadastros, ingestão, inferência, visualização e trilha
de histórico/auditoria. O escopo não inclui posicionamento contínuo, homologação
hospitalar ou implantação pública nesta entrega.

## Mapeamento do enunciado aos materiais

| Requisito do Marco 2 | Material preparado | Complemento do autor |
|---|---|---|
| Desenvolvimento técnico | [Guia do código](../reference/code-guide.md), docstrings e referência pydoc | Descrever participação e processo de desenvolvimento |
| Tecnologias e recursos | [README](../../README.md#tecnologias-e-organização), requisitos e Dockerfile | Inventariar hardware real, tags, cabos e instrumentos usados |
| Arquitetura e fluxos | [Arquitetura com leitores e simulador](../architecture/system-overview.md) e [modelo de dados](../architecture/data-model.md) | Inserir layout físico medido e fotos do ensaio |
| Funcionalidades/parâmetros operantes | Tabela abaixo, [parâmetros iniciais](../architecture/system-overview.md#inferência-e-projeção) e [validações](../operations/validation.md) | Identificar o cenário efetivamente demonstrado |
| Limitações do MVP | Seção de limites abaixo e limites de persistência na arquitetura | Relacionar aos objetivos acadêmicos |
| Testes internos iniciais | [Experimentos](../experiments/README.md), regressões, migrations e [registro desta versão](../operations/validation.md) | Acrescentar novas observações datadas |
| Evidência demonstrável | Roteiro abaixo e capturas já existentes | Gravar vídeo, conferir fotos e vincular o commit/tag entregue |

## Funcionalidades e nível de evidência

| Recurso | Evidência disponível | O que ainda precisa ser demonstrado/medido |
|---|---|---|
| Recepção e normalização MQTT | Testes automatizados e registros locais/gerenciados | Firmware e transporte do leitor no cenário institucional escolhido |
| Leituras idempotentes e recuperação | PostgreSQL/Mosquitto descartáveis e ensaios de resiliência | Comportamento com carga e interrupções reais de campo |
| Passagem, direção e última zona | Testes de regras e integração; ensaio sintético A→B documentado | Calibração física das janelas e taxa de acerto por cenário |
| Cadastros e associação EPC | Testes de domínio/API com constraints PostgreSQL | Conferir inventário do piloto e identificação física das tags |
| Interface, mapas, busca e leituras | Testes React, build e capturas de implementação | Registrar a demonstração com a configuração final do ensaio |
| Sessão, perfis e auditoria | Testes de autenticação, autorização, administração e concorrência | Adequação institucional para uso fora do laboratório |
| Leitor Identix EZ700 | [Relatório histórico de comunicação](../experiments/mqtt/test1_readers_communication.pdf) e [payload físico relatado](../implementations/hotfix-ez700-contador-timestamp.md) | Homologação integral do pipeline com hardware e rede do hospital |
| Antenas e alcance | Modelo ilustrativo do simulador | Alcance, orientação, potência, perdas, taxa de leitura e sobreposição reais |

Não há resultados de ganho, impedância, casamento de antena ou alcance medido
atribuíveis à nova versão. Só inclua essas grandezas se houver instrumentação e
registro de bancada correspondentes. O projeto de software usa antenas/leitores;
não declara desenvolvimento ou caracterização de uma antena própria.

## Roteiro de demonstração reproduzível

1. Registrar commit, versão, data, sistema operacional e origem dos dados.
2. Seguir a [instalação e execução](../operations/execution.md); escolher modo 1
   para demonstração sintética ou modo 2 com hardware configurado.
3. Após migrations, criar o administrador e entrar no dashboard. Gerar pelo
   simulador equipamentos chamados “Bomba 1”, “Bomba 2” e “Bomba 10”. No modo
   físico cadastrar EPCs reais com esses nomes ou nomes do inventário piloto.
4. Abrir o mapa EASY e a página de leituras. Apresentar a diferença entre presença
   na antena e última zona confirmada.
5. Mover um item de A para B dentro da janela e aguardar consolidação/inferência.
   Conferir passagem, direção, histórico e zona de destino. Repetir B→A após o
   período refratário. No modo físico registrar o trajeto e a orientação da tag.
6. Manter dois itens em leitura; demonstrar que novas leituras não invertem a
   ordem alfabética/numérica dentro do grupo. Retirar uma tag e aguardar 30 s
   para mostrar a expiração da presença.
7. Abrir detalhe e histórico. Com permissão administrativa, demonstrar correção
   justificada e o registro correspondente na auditoria.
8. Capturar telas e um vídeo contínuo curto identificando claramente “simulador”
   ou “leitor físico”. Encerrar pelo launcher e conservar as evidências sanitizadas.

## Evidências existentes para selecionar

- [Simulador visual](../implementations/assets/simulador-visual-laboratorio.png)
- [Leituras por antena](../implementations/assets/hotfix-leituras-pagina.png)
- [Mapa com presença](../implementations/assets/hotfix-leituras-mapa.png)
- [Dashboard](../implementations/assets/hotfix-leituras-dashboard.png)
- [Auditoria na interface](../implementations/assets/admin-auditoria-mobile.jpg)
- [Validação sintética de ingestão e projeção](../experiments/ingestion/sprint2-revisao-sintetica-2026-09-26.md)
- [Registro sintético desta candidata: 12 leituras e passagem A→B](../experiments/ingestion/marco2-candidata-2026-10-15.json)
- [Índice dos experimentos e relatórios históricos](../experiments/README.md)

As capturas são registros anteriores às últimas alterações desta candidata;
confira sua correspondência antes de usá-las como imagem da versão entregue.
Não há vídeo novo ou fotografia de hardware produzidos pela preparação do release.

## Ficha para novos ensaios físicos

| Campo | Preencher durante o ensaio |
|---|---|
| Data, responsável e local | — |
| Commit/versão e parâmetros de inferência | — |
| Modelo/firmware/serial do leitor | — |
| Modelo, porta, orientação e potência das antenas | — |
| Tipo/posição da tag e material do equipamento | — |
| Rede, broker, QoS e origem temporal | — |
| Distância e percurso medidos | — |
| Número de passagens por sentido | — |
| Leituras, acertos de direção, ambiguidades e perdas | — |
| Latência e método de medição | — |
| Fotos/vídeos/registros sanitizados | — |

## Limitações e evolução posterior

Localização por zona não garante que o equipamento permaneça nela. “Em trânsito”
é um rótulo de recência, sem sensor de movimento. A planta é esquemática.
Contador e RSSI físicos não têm unidades presumidas; tempo de recepção inclui
atrasos de transporte. Debounce e propostas ainda em memória não têm reconstrução
completa após reinício. Filas internas, armazenamento bruto e polling precisam
de avaliação de capacidade/retenção antes de aumentar o piloto.

Calibração física, aceite na rede do HUPAA, política institucional de acesso,
monitoramento, backup, retenção e hospedagem são evoluções posteriores. A hospedagem
fica para planejamento **após 16/10/2026**, conforme o escopo solicitado. O material
preparado não provisiona infraestrutura pública nem altera o nome remoto do repositório.

## Identificar a entrega

Use o nome público “Rastreamento RFID HUPAA”. Para uma futura renomeação do
repositório, o slug sugerido é `rastreamento-rfid-hupaa`. Os links de documentação
são relativos e acompanham a mudança. Atualize o endereço de `origin` depois da
renomeação efetiva; nenhum comando de execução depende do nome da pasta clonada.
Registre o link real do repositório e da versão entregue no documento final.
