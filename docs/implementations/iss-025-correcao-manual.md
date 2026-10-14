# ISS-025 — Correção manual de cadastro e localização (issue #27)

## O que é e por que importa

A localização vem do RFID, e o cadastro vem de quem digitou. Os dois erram: um equipamento sai da zona sem passar por um portal, um patrimônio é digitado trocado. Até aqui o patrimônio era **imutável** (o PATCH nem aceita o campo) e a correção de localização existia só como serviço interno, sem API, interface nem trilha de quem a fez.

Esta issue dá ao administrador, no painel de detalhes do equipamento, duas correções **justificadas, revisadas antes de gravar e auditadas**:

- **localização**: move a última zona e entra no histórico como `correcao_manual`;
- **cadastro**: nome, tipo, descrição e **patrimônio**. É a única forma de corrigir o patrimônio.

## Decisões

- O cadastro corrigível é nome, tipo, descrição e identificador interno (patrimônio). O PATCH comum continua sem o patrimônio.
- A concorrência é controlada por **uma** coluna `versao` no equipamento, incrementada por **qualquer** escrita.
- A correção de localização vale **a partir de agora**, no horário do servidor. Não retroage.
- A interface fica no painel de detalhes do equipamento e aparece só para quem tem `equipamentos:corrigir`, ou seja, só para o administrador.

## Versão otimista

`equipamentos.versao` (BIGINT, começa em 1) sobe a cada escrita:

- **ORM** (`version_id_col` do mapper): todo UPDATE do SQLAlchemy vira `UPDATE ... SET versao = versao + 1 WHERE id = :id AND versao = :lida`. Se outra transação gravou no meio, nenhuma linha casa e o SQLAlchemy levanta `StaleDataError`. Um handler global da API transforma isso em **409 `conflito_de_versao`**: é a rede de segurança para qualquer escrita, não só a correção.
- **Pipeline e correção de localização**: os dois movem a projeção pelo mesmo ponto único, `rfid_location.repository.update_location`, que faz `versao = versao + 1 ... RETURNING versao`.
- **Quem corrige** lê o equipamento (com a versão), revisa e envia `versao_esperada`. O serviço **trava** a linha (`FOR UPDATE` / `FOR NO KEY UPDATE`) antes de conferir. Se a versão mudou, devolve 409 com `versao_atual` e não grava nada. Duas correções simultâneas se serializam no lock: exatamente uma vence.

**Consequência conhecida:** como a versão é única para a linha toda, uma passagem do pipeline enquanto alguém edita o **nome** também gera conflito, embora não toque no nome. A pessoa revisa os valores recarregados e confirma de novo. É o preço de uma única versão simples, e é raro porque a edição dura segundos.

## API

Exige `equipamentos:corrigir` (só administrador). Sem sessão, 401; operacional, 403 `acesso_negado` (auditado). Corpo com `extra="forbid"`: campo desconhecido é 422.

```http
POST /equipamentos/12/correcoes/localizacao
{"zona_id": 7, "justificativa": "Vista na sala D pela enfermagem",
 "referencia": "OS-123", "versao_esperada": 5}

200 {"equipamento_id": 12, "zona_anterior_id": 3, "zona_id": 7, "movimentacao_id": 88,
     "movimentada_em": "2026-10-05T14:00:00Z", "versao": 6}
```

```http
POST /equipamentos/12/correcoes/cadastro
{"identificador_interno": "PAT-101", "justificativa": "Patrimônio trocado no cadastro",
 "versao_esperada": 6}

200 <EquipamentoResposta, agora com ultima_zona_id e versao>
```

- `justificativa`: obrigatória, até 1000 caracteres, com strip.
- `referencia`: opcional, até 255 caracteres; vazia vira nula.
- `versao_esperada`: ≥ 1.
- Cadastro: `nome`, `tipo_id`, `identificador_interno` e `descricao` são opcionais, e **só os diferentes do atual mudam**. `descricao: null` limpa. Nome e patrimônio não podem ficar vazios.

Erros no formato `{"detail": {"codigo": ..., "mensagem": ...}}`:

| Status | `codigo` | Quando |
|---|---|---|
| 404 | `equipamento_inexistente` | id não existe |
| 409 | `conflito_de_versao` (+ `versao_atual`) | versão mudou desde a leitura (PATCH, outra correção, passagem do pipeline) |
| 409 | `equipamento_inativo` | localização de equipamento inativo |
| 409 | `identificador_duplicado` | patrimônio já usado por outro equipamento |
| 409 | `anterior_a_ultima_localizacao` | última detecção registrada é posterior a agora |
| 409 | `conflito_de_horario` | última detecção no mesmo instante |
| 422 | `sem_mudanca` | mesma zona, ou nenhum campo diferente do atual |
| 422 | `zona_invalida` | zona inexistente ou inativa |
| 422 | `tipo_invalido` | tipo inexistente ou inativo |

## Interface

No painel de detalhes, a seção **Correção manual** aparece só para quem tem `equipamentos:corrigir` (o front lê de `/auth/me`) e tem os botões **Corrigir localização** e **Corrigir cadastro**.

1. O painel carrega o valor atual e a versão. A localização mostra o bloco "Localização atual"; o cadastro mostra "(atual: …)" em cada campo. As zonas aparecem como "Andar › Setor › Zona", porque há nomes de zona repetidos entre setores.
2. Justificativa obrigatória e referência opcional.
3. **Revisar correção** mostra a tabela "Atual / Corrigido" só com o que muda, **sem gravar**. Se nada mudou: "Nada a corrigir".
4. **Confirmar correção** envia só os campos alterados mais a `versao_esperada` vista.
5. **Conflito (409):** o painel recarrega o atual e a versão. **Só os campos que a pessoa editou mantêm o valor escolhido; os outros voltam ao valor atual.** Sem isso, o formulário guardaria o valor velho de um campo que a outra operação mudou, e a segunda confirmação apagaria essa mudança em silêncio. Exemplo: alguém corrige o patrimônio, outra pessoa muda a descrição no meio; depois do conflito a descrição nova aparece no formulário e não é enviada.
6. Outros erros voltam para a edição com a mensagem e preservam o que foi digitado.
7. Depois do sucesso: mensagem, o histórico abre na primeira página (com "(ref. X)" depois da justificativa) e o painel dispara a **atualização global** da ISS-033. Detalhe, histórico, lista e mapa recarregam na hora, sem esperar o ciclo de 2 s.
8. O detalhe aberto é recarregado **pelo ID** (`GET /api/ativos/{id}`), e não por busca textual. Depois de corrigir o patrimônio para algo genérico (por exemplo "1"), a busca paginada por nome ou patrimônio pode não trazer o equipamento na primeira página, e o painel continuaria mostrando os dados antigos (achado na revisão do PR #77).

### `GET /api/ativos/{id}`

Devolve um ativo no **mesmo formato** dos itens de `GET /api/ativos`, com zona, recência, EPC e última leitura, ou 404. Exige `equipamentos:consultar`, liberado ao operacional. O painel de detalhe usa essa rota em toda atualização, não só depois de uma correção.

## Migration `b025a1b2c3d4` (filha de `e028a1b2c3d4`)

- **Upgrade:**
  - `equipamentos.versao`: BIGINT NOT NULL, default 1, CHECK `ck_equipamentos_versao_positiva`;
  - `historico_movimentacoes.referencia`: varchar(255), CHECK `ck_historico_referencia_so_manual` (só em `correcao_manual`, e não vazia).
- **Downgrade:** antes de remover a coluna, a referência vai para o fim da justificativa (`… [referência: OS-123]`) nas linhas que a têm. Depois as CHECKs e as colunas são removidas.

## Como funciona

**Localização** (`api/service_correcoes.corrigir_localizacao_equipamento`):
1. trava o equipamento **antes** de conferir o status;
2. confere se existe, se está ativo e se a zona existe e está ativa;
3. chama `rfid_location.service.corrigir_localizacao`, que roda na transação de quem chama e faz, em ordem: fuso → lock → existência → versão → mesma zona → horário → ledger (`append_manual_correction`, com `registro_anterior_id` e referência) → projeção (`update_location`, versão +1);
4. grava `auditoria.registrar("correcao_manual")` com autor, motivo = justificativa, e antes/depois de zona e horário;
5. faz **um** commit. Qualquer recusa faz rollback.

O serviço interno `LocationProjectionService.apply_manual_location_correction` delega à mesma função.

**Cadastro** (`corrigir_cadastro`):
1. `SELECT ... FOR UPDATE` com `populate_existing`;
2. confere a versão;
3. calcula só os campos diferentes (tipo novo validado como ativo; patrimônio novo atualiza também o normalizado). Sem diferença, `sem_mudanca`;
4. `definir_correcao` marca a sessão, e o **registro central** da [ISS-028](iss-028-auditoria.md) grava a alteração como **uma** linha `correcao_manual`, com motivo e referência, em vez de `atualizar`. `encerrar_correcao` roda sempre em `finally`, para a marca não vazar na sessão.

A projeção de localização e `versao` não entram em `dados_antes`/`dados_depois`: não são cadastro.

## Testes e evidências

- **`tests/test_correcoes.py`** (login real):
  - ledger, projeção, resposta e auditoria exatos;
  - referência em `/movimentacoes`;
  - segunda correção encadeada;
  - recusas sem gravar nada;
  - 422 do corpo;
  - conflito:
    - versão velha;
    - PATCH no meio;
    - passagem do pipeline;
    - duas correções simultâneas;
    - `StaleDataError` vira 409;
    - correção **esperando o lock** e recusando depois do commit;
  - rollback quando a auditoria ou a projeção falham;
  - autorização com `acesso_negado` auditado;
  - cadastro com **uma** linha `correcao_manual`, patrimônio novo buscável e o PATCH seguinte de volta a `atualizar`;
  - recusas de cadastro;
  - marca que não vaza;
  - `versao` fora da trilha;
  - strip da referência no uso interno.
- **`tests/test_migration_iss025.py`**: legado recebe versão 1; as CHECKs disparam; downgrade preserva a referência na justificativa; reupgrade e `alembic check`.
- **`frontend/src/test/Correcao.test.tsx`**:
  - permissão;
  - revisão sem gravar e corpo com a versão vista;
  - mesma zona;
  - conflito com a versão nova;
  - erro de regra;
  - cadastro só com o que mudou;
  - conflito que **não desfaz** o campo mudado pela outra operação.
- **Mutação:**
  - backend: 16 regras quebradas de propósito, todas pegas. A que sobreviveu na primeira rodada (strip da referência no ledger, mascarado pelo schema da API) ganhou teste direto;
  - frontend: 5 mutações do painel, todas pegas.
- **Smoke E2E no Chromium** (Vite com proxy e uvicorn):
  - correção de localização com referência, que aparece no histórico como "Correção manual … (ref. …)", e a lista atualizada;
  - correção de patrimônio com um PATCH de descrição em paralelo: aviso de conflito com a descrição nova no formulário, e na segunda confirmação o patrimônio corrigido **com a descrição preservada no banco**;
  - `/auditorias?acao=correcao_manual` com 2 linhas, autor e motivo.

## Limites

- **Correções de cadastro** ficam na trilha (`GET /auditorias?acao=correcao_manual`) e na [tela complementar de auditoria](iss-026-028-frontend-administracao.md). O histórico do painel mostra só movimentações.
- **A correção não retroage**: vale a partir de agora. Não reescreve movimentos passados nem corrige uma detecção anterior.
- **Não mexe em vínculo de EPC**: troca de tag continua pelas rotas de associação.
- **`versao_esperada` só é opcional no uso interno** (`corrigir_localizacao` e `apply_manual_location_correction`); na API é obrigatória.
- Correção de cadastro de equipamento **inativo** é permitida (o patrimônio de um equipamento baixado pode estar errado); a de localização não.
