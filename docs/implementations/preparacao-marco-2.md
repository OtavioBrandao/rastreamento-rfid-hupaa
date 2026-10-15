# Preparação da versão funcional e documentação do Marco 2

## Problema e importância

O README descrevia uma etapa antiga de implementação e misturava catálogo de
issues com instruções de uso. Perfis, dependências e arquivos Docker dispersos na
raiz dificultavam a reprodução; faltavam descrições Python para documentar toda
a implementação com pydoc. Isso prejudicava a demonstração e a redação técnica.

## Solução

- Nome público “Rastreamento RFID HUPAA”, mantendo contratos de dados existentes.
- Configuração e exemplos em `config/`, requisitos em `requirements/`, Compose e
  Dockerfile em `deploy/`, Makefile em `scripts/`.
- Ajuste de caminhos em launcher, observadores, scripts, migrations, testes e CI.
- Perfis privados movidos localmente e preservados fora do índice do Git.
- README centrado no projeto, objetivos, execução, tecnologias e diagramas separados.
- Referência de módulos e docstrings para classes/funções/métodos do produto.
- Gerador pydoc com índice e suplemento de definições privadas; imports não abrem menu.
- Guias de operação, validação, limites e material do Marco 2, sem fabricar medições.
- Versão candidata `0.1.0-rc.1` na API e no frontend; notas de release preparadas.

`.gitignore` e `.gitattributes` precisam permanecer na raiz para proteger todo o
repositório e manter shell em LF. `AGENTS.md` permanece para orientar ferramentas
em todo o projeto. O README é o único documento de apresentação na raiz; os
demais documentos técnicos estão em `docs/`. Diretórios de pacotes permanecem
com os nomes originais para manter imports e os comandos `python -m` estáveis.

Os documentos de implementação históricos conservam os resultados de suas datas;
referências a comandos/caminhos foram ajustadas onde aplicável. O índice atual
direciona a operação para os novos guias, distinguindo evidência histórica de
validação da candidata. Nenhuma implantação hospitalar ou pública faz parte desta preparação.

## Validação

O registro verificável desta mudança está em [validações](../operations/validation.md).
A correção de prioridade tem [documento próprio](ordenacao-estavel-tabelas.md).
