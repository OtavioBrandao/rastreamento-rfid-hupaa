# ISS-027 — Perfis operacional e administrador / RBAC (issue #29)

## O que é a issue e por que importa

A ISS-026 entregou login, mas 69 das 80 rotas de API continuavam abertas sem sessão: qualquer pessoa na rede do HUPAA podia consultar e **alterar** cadastro de equipamentos, zonas e hardware. Esta issue exige **sessão e permissão em toda rota de negócio**, com dois perfis:

- **Operacional** — a equipe que consulta onde estão os equipamentos: **consulta tudo, exceto usuários, e não altera nada**. Isso inclui hardware/topologia (leitores, antenas, portais, mapeamentos) e as leituras do laboratório.
- **Administrador** — faz tudo, inclusive administrar usuários.

O dashboard ganhou login, a tela de troca de senha obrigatória e o botão Sair. **Não** há tela de administração de usuários (decisão da issue): a administração continua pela API.

## Matriz (permissão × perfil)

A matriz existe em **um só lugar**: `api/permissoes.py` (`Permissao` e `MATRIZ`). O front não a copia; `/auth/me` e o login devolvem `permissoes` já resolvidas.

| Permissão | Cobre | Operacional | Administrador |
|---|---|---|---|
| `equipamentos:consultar` | equipamentos, tipos, vínculo de EPC, busca, dashboard, histórico de movimentações | ✓ | ✓ |
| `equipamentos:alterar` | idem, escrita | — | ✓ |
| `localizacao:consultar` | andares, setores, zonas, árvore | ✓ | ✓ |
| `localizacao:alterar` | idem, escrita | — | ✓ |
| `hardware:consultar` | leitores, antenas, portais, mapeamentos, topologia | ✓ | ✓ |
| `hardware:alterar` | idem, escrita (e a escrita do laboratório, que hoje não existe) | — | ✓ |
| `laboratorio:consultar` | leituras brutas: `/api/laboratorio/leituras` e `/api/leituras/resumo` (página Leituras) | ✓ | ✓ |
| `usuarios:administrar` | todo `/usuarios` | — | ✓ |

## Regras gerais

- **Negado por padrão**: um perfil que não esteja em `MATRIZ` não tem permissão nenhuma. Ele entra (login 200, `permissoes: []`), mas recebe 403 em toda rota de negócio.
- **Públicas**: só `GET /health`, `POST /auth/login` e `POST /auth/logout`. `GET /auth/me` e `POST /auth/trocar-senha` aceitam qualquer sessão, inclusive com senha temporária.
- **Senha temporária barra antes da permissão**: as fábricas partem de `sessao_liberada`, então até a consulta responde 403 `troca_de_senha_obrigatoria`.
- **Respostas**: sem sessão → 401 `{"detail": "nao_autenticado"}`; sem permissão → 403 `{"detail": "acesso_negado"}`, **única** para todo o sistema. Isso inclui o caso raro de um administrador rebaixado enquanto sua própria requisição esperava o lock (`AutorSemPermissao`).
- **Método define a ação** nos routers de negócio: GET/HEAD/OPTIONS exigem a permissão de consulta; qualquer outro método, a de alteração.

## Rotas por permissão

Tabela **gerada por introspecção** com `python -m tools.tabela_permissoes`; regenere em vez de editar à mão. As rotas de documentação do FastAPI (`/docs`, `/redoc`, `/openapi.json`) não são rotas de API e ficam fora (ver limites).

| Método | Rota | Exige | Operacional | Administrador |
|---|---|---|---|---|
| GET | `/andares` | localizacao:consultar | ✓ | ✓ |
| POST | `/andares` | localizacao:alterar | — | ✓ |
| GET | `/andares/{andar_id}` | localizacao:consultar | ✓ | ✓ |
| PATCH | `/andares/{andar_id}` | localizacao:alterar | — | ✓ |
| GET | `/andares/{andar_id}/arvore` | localizacao:consultar | ✓ | ✓ |
| POST | `/andares/{andar_id}/inativar` | localizacao:alterar | — | ✓ |
| POST | `/andares/{andar_id}/reativar` | localizacao:alterar | — | ✓ |
| GET | `/antenas` | hardware:consultar | ✓ | ✓ |
| POST | `/antenas` | hardware:alterar | — | ✓ |
| GET | `/antenas/{antena_id}` | hardware:consultar | ✓ | ✓ |
| PATCH | `/antenas/{antena_id}` | hardware:alterar | — | ✓ |
| POST | `/antenas/{antena_id}/inativar` | hardware:alterar | — | ✓ |
| GET | `/antenas/{antena_id}/mapeamentos` | hardware:consultar | ✓ | ✓ |
| POST | `/antenas/{antena_id}/reativar` | hardware:alterar | — | ✓ |
| GET | `/api/ativos` | equipamentos:consultar | ✓ | ✓ |
| GET | `/api/dashboard/atividade` | equipamentos:consultar | ✓ | ✓ |
| GET | `/api/dashboard/resumo` | equipamentos:consultar | ✓ | ✓ |
| GET | `/api/laboratorio/leituras` | laboratorio:consultar | ✓ | ✓ |
| GET | `/api/leituras/resumo` | laboratorio:consultar | ✓ | ✓ |
| POST | `/auth/login` | pública | ✓ | ✓ |
| POST | `/auth/logout` | pública | ✓ | ✓ |
| GET | `/auth/me` | qualquer sessão | ✓ | ✓ |
| POST | `/auth/trocar-senha` | qualquer sessão | ✓ | ✓ |
| GET | `/equipamentos` | equipamentos:consultar | ✓ | ✓ |
| POST | `/equipamentos` | equipamentos:alterar | — | ✓ |
| GET | `/equipamentos/por-identificador/{identificador_interno}` | equipamentos:consultar | ✓ | ✓ |
| GET | `/equipamentos/{equipamento_id}` | equipamentos:consultar | ✓ | ✓ |
| PATCH | `/equipamentos/{equipamento_id}` | equipamentos:alterar | — | ✓ |
| POST | `/equipamentos/{equipamento_id}/inativar` | equipamentos:alterar | — | ✓ |
| GET | `/equipamentos/{equipamento_id}/movimentacoes` | equipamentos:consultar | ✓ | ✓ |
| POST | `/equipamentos/{equipamento_id}/reativar` | equipamentos:alterar | — | ✓ |
| DELETE | `/equipamentos/{equipamento_id}/tag` | equipamentos:alterar | — | ✓ |
| GET | `/equipamentos/{equipamento_id}/tag` | equipamentos:consultar | ✓ | ✓ |
| POST | `/equipamentos/{equipamento_id}/tag` | equipamentos:alterar | — | ✓ |
| PUT | `/equipamentos/{equipamento_id}/tag` | equipamentos:alterar | — | ✓ |
| GET | `/equipamentos/{equipamento_id}/tag/historico` | equipamentos:consultar | ✓ | ✓ |
| GET | `/health` | pública | ✓ | ✓ |
| GET | `/leitores` | hardware:consultar | ✓ | ✓ |
| POST | `/leitores` | hardware:alterar | — | ✓ |
| GET | `/leitores/{leitor_id}` | hardware:consultar | ✓ | ✓ |
| PATCH | `/leitores/{leitor_id}` | hardware:alterar | — | ✓ |
| POST | `/leitores/{leitor_id}/inativar` | hardware:alterar | — | ✓ |
| POST | `/leitores/{leitor_id}/reativar` | hardware:alterar | — | ✓ |
| GET | `/localizacoes/arvore` | localizacao:consultar | ✓ | ✓ |
| GET | `/mapeamentos-antena/{mapeamento_id}` | hardware:consultar | ✓ | ✓ |
| PATCH | `/mapeamentos-antena/{mapeamento_id}` | hardware:alterar | — | ✓ |
| POST | `/mapeamentos-antena/{mapeamento_id}/inativar` | hardware:alterar | — | ✓ |
| GET | `/portais` | hardware:consultar | ✓ | ✓ |
| POST | `/portais` | hardware:alterar | — | ✓ |
| GET | `/portais/{portal_id}` | hardware:consultar | ✓ | ✓ |
| PATCH | `/portais/{portal_id}` | hardware:alterar | — | ✓ |
| POST | `/portais/{portal_id}/inativar` | hardware:alterar | — | ✓ |
| GET | `/portais/{portal_id}/mapeamentos` | hardware:consultar | ✓ | ✓ |
| POST | `/portais/{portal_id}/mapeamentos` | hardware:alterar | — | ✓ |
| POST | `/portais/{portal_id}/reativar` | hardware:alterar | — | ✓ |
| GET | `/portais/{portal_id}/topologia` | hardware:consultar | ✓ | ✓ |
| GET | `/setores` | localizacao:consultar | ✓ | ✓ |
| POST | `/setores` | localizacao:alterar | — | ✓ |
| GET | `/setores/{setor_id}` | localizacao:consultar | ✓ | ✓ |
| PATCH | `/setores/{setor_id}` | localizacao:alterar | — | ✓ |
| POST | `/setores/{setor_id}/inativar` | localizacao:alterar | — | ✓ |
| POST | `/setores/{setor_id}/reativar` | localizacao:alterar | — | ✓ |
| GET | `/tags/{epc}` | equipamentos:consultar | ✓ | ✓ |
| GET | `/tipos-equipamento` | equipamentos:consultar | ✓ | ✓ |
| POST | `/tipos-equipamento` | equipamentos:alterar | — | ✓ |
| GET | `/tipos-equipamento/{tipo_id}` | equipamentos:consultar | ✓ | ✓ |
| PATCH | `/tipos-equipamento/{tipo_id}` | equipamentos:alterar | — | ✓ |
| POST | `/tipos-equipamento/{tipo_id}/inativar` | equipamentos:alterar | — | ✓ |
| POST | `/tipos-equipamento/{tipo_id}/reativar` | equipamentos:alterar | — | ✓ |
| GET | `/usuarios` | usuarios:administrar | — | ✓ |
| POST | `/usuarios` | usuarios:administrar | — | ✓ |
| GET | `/usuarios/{usuario_id}` | usuarios:administrar | — | ✓ |
| PATCH | `/usuarios/{usuario_id}` | usuarios:administrar | — | ✓ |
| POST | `/usuarios/{usuario_id}/desativar` | usuarios:administrar | — | ✓ |
| POST | `/usuarios/{usuario_id}/reativar` | usuarios:administrar | — | ✓ |
| POST | `/usuarios/{usuario_id}/redefinir-senha` | usuarios:administrar | — | ✓ |
| GET | `/zonas` | localizacao:consultar | ✓ | ✓ |
| POST | `/zonas` | localizacao:alterar | — | ✓ |
| GET | `/zonas/{zona_id}` | localizacao:consultar | ✓ | ✓ |
| PATCH | `/zonas/{zona_id}` | localizacao:alterar | — | ✓ |
| POST | `/zonas/{zona_id}/inativar` | localizacao:alterar | — | ✓ |
| POST | `/zonas/{zona_id}/reativar` | localizacao:alterar | — | ✓ |

82 rotas.

## Como funciona

### Backend

- `api/permissoes.py` tem duas fábricas de dependency, ambas em cima de `sessao_liberada`:
  - `exigir(permissao)`, para rota ou router com uma permissão fixa;
  - `exigir_por_metodo(consultar=..., alterar=...)`, para router.
  Cada dependency gerada carrega `permissoes_exigidas` (e, na por método, `permissao_consulta`/`permissao_alteracao`), que o teste de inventário e o gerador da tabela inspecionam.
- Cada router de negócio declara a exigência no próprio `APIRouter(..., dependencies=[Depends(_PERMISSAO)])`: associação, busca de ativos, dashboard, equipamentos e tipos (equipamentos); localização; hardware e topologia de portais (hardware); leituras do laboratório (consulta = laboratório, alteração = `hardware:alterar`). `router_auth` fica sem.
- `/usuarios` usa `administrar_usuarios = exigir(usuarios:administrar)` no router **e** nas rotas que precisam do autor. É o **mesmo objeto**, que o FastAPI resolve uma vez por request. `sessao_administrador` e o detail antigo `acesso_restrito_a_administradores` foram removidos.
- `UsuarioResposta.perfil` passou a `str`. Com o `Literal` dos dois perfis, um usuário com perfil fora da matriz derrubava o **login** com 500 na validação da resposta. As **entradas** (criar, editar, filtro) continuam restritas aos dois perfis.

### Interface

- `src/services/auth.ts` implementa sessão, entrar, sair, trocar senha, `pode(sessao, permissao)` e o evento `rfid:sessao-encerrada`. Todas as chamadas vão com `credentials: 'same-origin'`. O token nunca passa por estado, `localStorage`, `sessionStorage` nem header: ele só existe no cookie HttpOnly.
- No login, 401 e 422 viram a mesma mensagem, "E-mail ou senha inválidos.", e o campo de senha é limpo.
- O `App` tem três estados: carregando, sem sessão (tela de login) e com sessão.
  - Com `deve_trocar_senha`, abre a tela de troca: senha temporária, nova senha e confirmação. O mínimo de 8 caracteres e a confirmação são conferidos no front **antes** de chamar a API. A tela tem botão Sair.
  - Qualquer 401 nas consultas do painel (`readJson`) dispara o evento de sessão encerrada, e o app volta ao login com o aviso "Sua sessão expirou. Entre novamente.". Isso cobre expiração, conta desativada e logout em outra aba.
  - Servidor fora do ar na abertura leva ao login com aviso; o app nunca fica preso em "carregando".
- O cabeçalho mostra nome, rótulo do perfil e o botão Sair.
- O proxy do Vite passou a encaminhar `/auth`. `/usuarios` **não** é encaminhado, porque não há tela de usuários.

### Log

Cada negação gera, no logger `api.autorizacao`, o evento:

```json
{"evento": "acesso_negado", "usuario_id": 2, "perfil": "operacional",
 "permissao": "equipamentos:alterar", "metodo": "PATCH", "rota": "/equipamentos/{equipamento_id}"}
```

`rota` é o **molde** (`request.scope["route"].path`), não a URL concreta. O evento nunca leva cookie, token, query string nem corpo. Um 401 (sem sessão) não é registrado, e uma consulta permitida também não gera log.

## Como ampliar

- **Nova ação num recurso existente**: acrescente o membro em `Permissao`, conceda-o em `MATRIZ` e use `exigir(Permissao.NOVA)` na rota. Se a ação for escrita dentro de um router com `exigir_por_metodo`, a rota já herda a permissão de alteração; `exigir` na rota soma uma exigência mais estrita.
- **Novo router**: declare `dependencies=[Depends(exigir_por_metodo(consultar=..., alterar=...))]` no `APIRouter`. Sem isso, `test_toda_rota_nao_publica_declara_permissao` falha listando as rotas novas. Inclua o prefixo em `RECURSO_POR_PREFIXO` do `tests/test_rbac_matriz.py` e regenere a tabela acima.
- **Novo perfil**: insira a linha em `perfis` por migration e a entrada em `MATRIZ`. Enquanto não houver entrada na matriz, o perfil entra no sistema mas não acessa nada, e isso é intencional.

## Testes e evidências

- **`tests/test_rbac_matriz.py`** (login e cookie reais):
  - descobre as rotas por introspecção, com teste de sanidade de pelo menos 80;
  - falha listando rota não pública sem permissão;
  - confere se a permissão declarada bate com as decisões;
  - testa cada rota × anônimo/operacional/administrador contra a regra escrita a partir das decisões;
  - verifica que a negação não altera dados;
  - cobre senha temporária, perfil fora da matriz e as permissões do `/auth/me` e do login;
  - confere o log de negação (campos, sem token nem corpo) e que consulta permitida não gera log.
- **Testes antigos de CRUD**: o fixture autouse `administrador_de_teste` (`tests/conftest.py`) substitui `sessao_autenticada` por um administrador **transiente**, sem linha no banco. O opt-out é o marcador `autenticacao_real`, usado nos módulos da ISS-026 e da ISS-027. **ISS-028**: quando os serviços gravarem o autor, esse admin precisa virar uma linha real.
- **Frontend**: `src/test/Auth.test.tsx` cobre login, erros, senha temporária, sair, 401 no uso e servidor fora; o `App.test.tsx` agora espera o painel montar.
- **Mutação**: 21 regras quebradas de propósito, cada uma derrubando algum teste. A única sobrevivente, o detail do `AutorSemPermissao`, ganhou teste HTTP próprio.
- **Smoke em Chromium real**: API na 8000, Vite na 5173, 22 passos:
  - login, senha errada e troca de senha;
  - cookie `rfid_sessao` aceito em `http://localhost` com HttpOnly, Secure e SameSite=Strict, e ausente de `document.cookie`;
  - recarregar mantém a sessão;
  - operacional consulta (200) e escreve (403) pela API no navegador;
  - sair;
  - admin desativa a operadora e a próxima consulta dela volta ao login com aviso.

  O log da API teve os `acesso_negado` e nenhuma senha em claro; o `pg_dump` também não teve senha nenhuma.

## Limites

- `/docs`, `/redoc` e `/openapi.json` continuam públicos: expõem a **forma** da API, não dados. Fechá-los atrapalharia o desenvolvimento; se o deploy exigir, desligue-os na criação do `FastAPI`.
- A interface não esconde ações por permissão, porque hoje o painel só consulta. `pode()` fica pronto para quando houver ações de escrita na tela.
- Não há tela de administração de usuários: a administração é pela API (`/usuarios`), fora do proxy do Vite.
