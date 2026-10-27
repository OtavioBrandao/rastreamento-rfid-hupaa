# Limpeza segura do banco e preparação para deploy

## O problema

Depois do Marco 2 o banco de desenvolvimento acumulou leituras, passagens,
equipamentos de laboratório e topologias de teste; não havia forma segura de
voltar a um estado limpo sem perder usuários e auditoria. Também não havia
artefatos para hospedar o sistema: só o ingestor tinha imagem Docker, a API e
o frontend rodavam pelo `scripts/dev.py` no notebook.

## Importância para o MVP

Demonstrações ao hospital precisam começar de um banco limpo e confiável. E o
sistema implantado não pode depender do computador de desenvolvimento: precisa
de imagens, configuração de produção, sondas de saúde e um caminho de
implantação documentado, ainda que o provedor não esteja escolhido.

## O que foi feito

**Limpeza** — `tools/limpeza_banco.py` (prévia, executar, verificar), com
classificação explícita do que é descartável, travas de produção e banco
remoto, confirmação pelo nome do banco, transação única, preservação
conferida de usuários/perfis/auditoria e registro da própria limpeza na
trilha. Procedimento completo, backup e restauração em
[operations/limpeza-banco.md](../operations/limpeza-banco.md).

**Deploy** — estudo e recomendação em
[operations/deploy.md](../operations/deploy.md), e:

- `deploy/production/`: imagem única de backend (API, ingestor, migrations),
  imagem web (Nginx sem privilégios com proxy same-origin, CSP, limite de
  login), Compose de referência e allowlists de contexto Docker.
- `config/environments/.env.production.example` sem segredos.
- `APP_ENV` (development/demo/production), readiness `/health/ready`,
  cabeçalhos de segurança, verificação de `Origin` nas escritas, CORS
  opcional, cookie `Secure` obrigatório em produção, pool de conexões e
  logs JSON configuráveis.
- Modelo de bridge Mosquitto do hospital para o HiveMQ Cloud.
- Job de CI que valida o Compose de produção e constrói as imagens.

## Validação

- `tests/test_limpeza_banco.py` e `tests/test_deploy_config.py`.
- Smoke local das imagens de produção (migrate, api, web) contra PostgreSQL
  descartável, com verificação de origem, rate limit, usuário sem root e
  sistema de arquivos somente leitura. Nenhum deploy real foi feito.
- Limpeza executada apenas no PostgreSQL local isolado, com backup prévio.
