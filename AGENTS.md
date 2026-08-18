# Orientações para agentes

- Leia o `README.md` da raiz e a documentação do experimento relevante antes de alterar código.
- Preserve o escopo experimental e local-first do projeto.
- Não presuma o protocolo nem o formato de payload do Identix EZ700 antes da validação física.
- Nunca registre credenciais, tokens ou senhas MQTT no repositório.
- Execute as validações relevantes antes de criar um commit.
- Mantenha a documentação em português, salvo se uma issue futura solicitar outro idioma.
- Os scripts shell têm como alvo o Ubuntu 24.04 e devem usar finais de linha LF.
- Não configure o notebook como hotspot; ele atua somente como broker e receptor MQTT.
