# Cabeçalhos repassados à API. Host original: a verificação de Origin da API
# compara o Origin do navegador com este Host.
proxy_http_version 1.1;
proxy_set_header Host $http_host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Correlation-ID $request_id;
proxy_connect_timeout 5s;
proxy_read_timeout 30s;
