# ADR 0009 — Autenticação por Sessão Opaca em Cookie e Senhas Argon2id

## Status
Aceito e implementado (ISS-026, issue #28)

## Contexto
Até a ISS-026 a API não tinha login: as tabelas `usuarios`, `perfis` e `auditorias` existiam desde o schema inicial, mas nada as usava e `perfis` estava vazia. O MVP precisa de contas nominais para a equipe do HUPAA e de uma forma de administrá-las, com as restrições do projeto:

- **local-first e sem serviços externos** (nada de provedor de identidade);
- API e frontend servidos na **mesma origem** no MVP;
- a equipe precisa conseguir **encerrar o acesso na hora**: ao desligar alguém, trocar ou redefinir a senha;
- nenhum segredo em log, resposta ou repositório.

A autorização por perfil nas demais rotas fica para a ISS-027, e o catálogo de auditoria para a ISS-028.

## Decisão
1. **Sessão com token opaco no banco, não JWT.** O login gera 256 bits aleatórios (`secrets.token_urlsafe(32)`). O banco guarda só o SHA-256 em hex (`sessoes.token_hash`, UNIQUE, com CHECK de formato). Validar uma request custa uma consulta por índice único.
2. **Token só em cookie `rfid_sessao`** com `HttpOnly`, `Secure` (configurável), `SameSite=Strict`, `Path=/` e `Max-Age` igual à duração da sessão. Não existe header `Authorization`.
3. **Sessão válida = não revogada, não expirada e usuário ativo**, conferido a cada request. Desativar também revoga as sessões, de modo que as duas defesas cobrem inclusive uma desativação feita direto no banco.
4. **Login por e-mail normalizado** (minúsculas, sem espaço nas pontas). Uma CHECK no banco garante a normalização. Os e-mails aceitos na criação são só ASCII, para a regra de minúsculas do Python e a do Postgres coincidirem.
5. **Senha com Argon2id** (`argon2-cffi`, parâmetros padrão da biblioteca). Hash ilegível ou de formato legado recusa o login e nunca vira erro 500.
6. **Resposta de login recusado indistinguível**: sempre o mesmo 401 `credenciais_invalidas` e sempre **uma** verificação Argon2 completa. Quando a conta não existe, a verificação usa um hash fictício, para o tempo de resposta não revelar quais e-mails estão cadastrados.
7. **Bloqueio por conta**: após N falhas seguidas, a conta fica bloqueada por M minutos e o contador zera. Durante o bloqueio nem a senha certa entra. A linha do usuário é travada (`FOR UPDATE`) no login, para falhas simultâneas serem todas contadas.
8. **Senha temporária com troca obrigatória.** O administrador define a senha ao criar ou redefinir uma conta. Até a troca, a sessão só acessa `/auth/me`, `/auth/trocar-senha` e `/auth/logout`. O resto responde 403 `troca_de_senha_obrigatoria`. O primeiro administrador nasce por comando de terminal, sem troca obrigatória.
9. **Ordem fixa de locks na administração**: primeiro os administradores ativos, em ordem de id, e depois o alvo. Isso impede deadlock e garante que sempre reste um administrador ativo.

## Alternativas descartadas
- **JWT sem estado**: não há como revogar um token antes de ele expirar sem manter uma lista de revogação no banco, e aí se perde a vantagem de não ter estado. Encerrar o acesso na hora é requisito.
- **JWT ou token em `localStorage` com header `Authorization`**: qualquer XSS lê o token. Com cookie `HttpOnly`, o script da página nunca o vê.
- **Guardar o token em claro**: um vazamento de backup ou `pg_dump` viraria sequestro de sessão. Com só o SHA-256 guardado, o dump não reapresenta sessão. Um hash lento é desnecessário porque o token já tem 256 bits de entropia.
- **bcrypt / PBKDF2**: funcionam, mas o Argon2id é o recomendado atual (OWASP), resiste a GPU por exigir memória e tem biblioteca madura em Python.
- **Login por nome de usuário**: seria mais um identificador para normalizar e manter único. A coluna `email` já existia e é única.
- **Senha inicial gerada e enviada por e-mail**: o MVP não tem servidor de e-mail. O administrador entrega a senha temporária por canal próprio, e a troca obrigatória limita a exposição.

## Limites assumidos
- **Bloqueio por conta, não por IP.** Um atacante pode bloquear a conta de alguém de propósito, errando a senha N vezes (negação de serviço dirigida). Em troca, o bloqueio não depende de IP, que no hospital pode ser compartilhado por NAT ou proxy. Limitar a taxa por IP fica para quando existir um proxy reverso na frente da API.
- **CSRF coberto por `SameSite=Strict`** enquanto frontend e API estiverem na **mesma origem**. Se passarem a origens diferentes, com CORS e cookies de terceiros, será preciso um token anti-CSRF.
- **`Secure` configurável** (`SESSAO_COOKIE_SEGURO`): desligar é só para ferramentas de desenvolvimento por HTTP puro. Navegadores já tratam `http://localhost` como contexto seguro.
- **Sem limpeza de sessões antigas**: linhas revogadas ou expiradas ficam na tabela. O expurgo entra junto da política de retenção (RNF-015).
- **Sem MFA, recuperação por e-mail ou política de complexidade além do tamanho** (8 a 128 caracteres). São evoluções possíveis, fora do escopo do MVP.

## Consequências
- Cada request autenticada custa uma consulta por índice único em `sessoes`, com join em `usuarios` e `perfis`.
- A ISS-027 protegeu as rotas existentes a partir de `sessao_liberada`, com a matriz de `api/permissoes.py` (que substituiu `sessao_administrador`). O front conta com o detail `troca_de_senha_obrigatoria`.
- Mudar o formato do token ou do cookie invalida todas as sessões abertas, o que é aceitável: basta entrar de novo.
