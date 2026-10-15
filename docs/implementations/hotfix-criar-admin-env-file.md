# Correção — arquivo de ambiente no cadastro inicial

## Problema e importância para o MVP

O comando de criação do administrador carregava somente o `.env` padrão e as
variáveis já exportadas. A existência de `.env.cloud` não bastava: sem exportação
prévia, o cadastro falhava com `Nenhuma DATABASE_URL definida`, impedindo o primeiro
acesso ao MVP. A instrução com `source` também não funcionava no PowerShell.

## O que foi feito

- Adicionada a opção explícita `--env-file` ao comando `api.criar_admin`.
- O arquivo indicado é carregado antes da sessão de banco e da solicitação de
  senha; seus valores prevalecem sobre variáveis já exportadas no terminal.
- Sem a opção, mantido o comportamento de ambiente e `.env` padrão.
- Arquivo inexistente e URL ausente produzem erro orientativo sem traceback e
  sem exibir credenciais.
- Atualizados o README e o guia de autenticação com exemplos para PowerShell.

```powershell
.\.venv\Scripts\python.exe -m api.criar_admin --env-file .env.cloud --nome "Seu Nome" --email "seu@email.com"
```

A senha continua sendo digitada duas vezes no terminal, sem aparecer na tela.
Nenhuma conta ou senha padrão é criada pela correção.

## Validação

Os testes de `tests/test_criar_admin.py` cobrem leitura do arquivo, precedência,
erro de configuração antes da senha e criação por subprocesso usando
`--env-file` contra PostgreSQL local descartável. O fluxo existente também
verifica hash Argon2id, auditoria e login real pela API.

Resultado: **13 testes passaram** em PostgreSQL 16 descartável; lint Ruff e
`git diff --check` também passaram. A conexão usando o `.env.cloud` existente
foi verificada somente por consultas, sem criar usuários nem alterar seus dados.
