# ISS-051 — Reorganização da Estrutura e Padronização da Documentação do Projeto

Este documento registra a implementação da **Issue #51**, conforme a diretriz obrigatória de governança estabelecida em `AGENTS.md`.

---

## 1. O que é a Issue #51

A **Issue #51** visa reorganizar a árvore de documentação do repositório `OtavioBrandao/rfid-hospital-mvp`, padronizando o formato dos documentos técnicos, eliminando referências defasadas e estabelecendo um fluxo de leitura progressivo e intuitivo para desenvolvedores e para a apresentação acadêmica do MVP.

---

## 2. Importância para o MVP

Após a estabilização e merge das issues estruturantes do projeto (ISS-001 até ISS-012), a documentação encontrava-se fragmentada em múltiplos locais heterogêneos (`docs/database/`, `docs/infrastructure/`, `docs/evidence/`, raiz do repositório). Havia:
- Notas de implementação ricas misturadas com evidências empíricas e históricos de PRs.
- Declarações obsoletas (ex.: "PR #43 pendente", "PR #50 pendente", `event_id` referenciado como UUID anterior à migration canônica).
- Ausência de documentação dedicada para subsistemas cruciais recém-integrados (gestão de equipamentos, hierarquia hospitalar e topologia de hardware).
- Dificuldade para um avaliador ou desenvolvedor recém-chegado compreender de ponta a ponta como uma leitura RFID viaja pelo sistema e qual é o estado exato da entrega.

Com a apresentação iminente do projeto para a banca avaliadora e partes interessadas do HUPAA/UFAL, a documentação precisava ser tão profissional, confiável e auditável quanto o código-fonte.

---

## 3. O que foi feito para resolvê-la

A solução adotou uma abordagem metódica, estruturada e dividida em commits atômicos rastreáveis:

1. **Ponto de Entrada Único (`docs/README.md`):**
   - Criação de um guia completo e progressivo respondendo o que é o projeto, qual problema resolve, o que está implementado versus planejado, como uma leitura trafega no sistema e a ordem recomendada de leitura para apresentação e desenvolvimento.
2. **Estrutura Conceitual em Quatro Pilares:**
   - `docs/architecture/`: Documentos de visão geral de alto nível, modelos conceituais, entidades e diagramas Mermaid.
   - `docs/implementations/`: Guias de engenharia por subsistema e issue (incluindo consolidação da ISS-006, ISS-007, criação de guias para ISS-008..010, ISS-011 e ISS-012).
   - `docs/experiments/`: Reorganização de relatórios empíricos, logs de teste e evidências de rede/MQTT e ingestão, com distinção rigorosa entre testes com simuladores e validação física de campo.
   - `docs/decisions/`: Registros formais de decisões de arquitetura (ADRs leves) cobrindo tópicos como ACK manual, resiliência sem fila em memória, desacoplamento leitor-portal e unicidade parcial de antena ativa.
3. **Preservação de Histórico (`git mv`):**
   - Todas as movimentações de arquivos existentes foram executadas preservando o histórico do Git.
4. **Saneamento de Referências e Links:**
   - Correção de links internos quebrados, remoção de referências a branches e PRs antigos já mesclados na `main`.
5. **Alinhamento do `README.md` Raiz:**
   - Síntese prática e objetiva do projeto, com instruções de execução rápida e direcionamento imediato para `docs/README.md`.
