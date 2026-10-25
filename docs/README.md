# Documentação — Rastreamento RFID HUPAA

Referência técnica do MVP experimental de rastreamento por zonas para o Hospital
Universitário Professor Alberto Antunes (HUPAA/UFAL).

## Começar e reproduzir

- [Apresentação, objetivos e início rápido](../README.md)
- [Operação, requisitos, perfis e quatro modos de execução](operations/execution.md)
- [Piloto no HUPAA: planta, leitores, antenas, portais e cadastro das tags](operations/implantacao-hupaa.md)
- [Launcher de laboratório e simulador web](lab_test_launcher.md)
- [Preparação para implantação (deploy)](operations/deploy.md)
- [Limpeza segura do banco, backup e restauração](operations/limpeza-banco.md)
- [Validações e testes reproduzíveis](operations/validation.md)

## Compreender o software

- [Arquitetura com leitores, arquitetura com simulador e sequência de processamento](architecture/system-overview.md)
- [Modelo de dados e invariantes](architecture/data-model.md)
- [Diagrama entidade-relacionamento](architecture/er-diagrama.mermaid)
- [Guia dos módulos, contratos e geração pydoc](reference/code-guide.md)
- [Decisões arquiteturais](decisions/README.md)

## Problemas e soluções

Cada registro em `implementations/` explica o problema, sua importância para o MVP,
a solução e a validação disponível na data da mudança. Para os comandos atuais,
use o guia de operação acima; relatórios antigos registram o contexto do ensaio.

| Problema/tema | Detalhamento |
|---|---|
| Cadastros de sessões anteriores acumulados no painel | [Inventário operacional e consulta dos inativos](implementations/inventario-cadastros-inativos.md) |
| Silêncio ou falha de comunicação dos leitores | [Status por contato, heartbeat e agregação dos portais](implementations/iss-024-status-leitores.md) |
| Tabelas trocando posição a cada leitura | [Prioridade por grupos e ordenação estável](implementations/ordenacao-estavel-tabelas.md) |
| Documentação antiga e arquivos dispersos | [Organização e documentação técnica do repositório](implementations/organizacao-documentacao.md) |
| Recepção MQTT local e externa | [Ingestão e perfis de transporte](implementations/iss-001-mqtt-ingestion.md) |
| Eventos duplicados e confirmação de mensagens | [Persistência idempotente](implementations/iss-006-raw-readings-persistence.md) |
| Interrupções de broker e banco | [Recuperação do ingestor](implementations/iss-007-ingestor-resilience.md) |
| Contador e RSSI sem unidade validada | [Compatibilidade com o payload observado do EZ700](implementations/hotfix-ez700-contador-timestamp.md) |
| Latência do banco externo | [Gravação em lotes e threads de processamento](implementations/hotfix-ingestor-lotes-banco-remoto.md) |
| Cadastro e vínculo de EPC | [Equipamentos, tipos e associações](implementations/iss-008-009-010-equipamentos-epc.md) |
| Hierarquia do hospital | [Andares, setores e zonas](implementations/iss-011-localizacao-hospitalar.md) |
| Leitores, portas e antenas | [Topologia física de hardware](implementations/iss-012-topologia-hardware.md) |
| Configuração de lados e zonas no tempo | [Topologia lógica versionada](implementations/iss-013-topologia-logica-portais.md) |
| Leituras repetidas e passagens | [Debounce](implementations/iss-014-debounce-leituras.md), [passagem](implementations/iss-015-deteccao-passagem.md) e [direção](implementations/iss-016-inferencia-direcao.md) |
| Retorno entre antenas e sobreposição | [Passagens em vai e vem](implementations/hotfix-passagem-vai-e-vem.md) |
| Troca entre antenas atrasada ou perdida | [Transições atrasadas no simulador](implementations/hotfix-transicoes-atrasadas.md) |
| Histórico e última zona | [Movimentações](implementations/iss-018-historico-movimentacoes.md) e [projeção temporal](implementations/iss-017-ultima-localizacao.md) |
| Presença sem passagem confirmada | [Leituras e presença](implementations/hotfix-leituras-presenca.md) |
| Busca e ativos por zona | [Busca operacional](implementations/iss-019-busca-ativos.md) e [ativos por zona](implementations/iss-020-ativos-por-zona.md) |
| Localização antiga | [Critério de recência](implementations/iss-022-recencia-localizacao.md) |
| Planta e atualização da interface | [Mapa e portais](implementations/iss-023-mapa-portais.md) e [atualização automática](implementations/iss-033-atualizacao-automatica.md) |
| Correção justificada | [Correções manuais e versão otimista](implementations/iss-025-correcao-manual.md) |
| Acesso e responsabilização | [Autenticação](implementations/iss-026-usuarios-autenticacao.md), [permissões](implementations/iss-027-perfis-rbac.md) e [auditoria](implementations/iss-028-auditoria.md) |
| Demonstração sem hardware | [Simulador web EASY/HUPAA](implementations/simulador-web.md) (substitui o [simulador Flet](implementations/simulador-visual-laboratorio.md); [hotfix MQTT e visada](implementations/simulador-web-hotfix-mqtt-visada.md)) |
| Cadastro dependente do terminal | [Cadastro de equipamentos e tags pelo dashboard](implementations/cadastro-equipamentos-web.md) |
| Dados experimentais e hospedagem | [Limpeza segura e preparação para deploy](implementations/limpeza-banco-e-preparacao-deploy.md) |

## Evidências de funcionamento

- [Galeria do pipeline: dashboard, mapa EASY, leituras e histórico](experiments/galeria-pipeline.md)
- [Matriz de experimentos e evidências históricas](experiments/README.md)
- [Registros de implementações](implementations/)

Simulação, teste de integração e validação física são níveis distintos de
evidência. O registro de cada ensaio deve identificar a origem do resultado,
o commit utilizado e as medições efetivamente realizadas.
