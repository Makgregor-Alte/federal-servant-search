# Arquitetura

## Componentes

```text
Navegador                         Aplicativo desktop (Tkinter)
    |                                        |
    | HTTP :8080                             | HTTP :8080
    v                                        |
Nginx (frontend React/Vite) <----------------+
    |
    | Proxy /api/*
    v
Gunicorn / Flask (backend :5000)
    |
    | Psycopg 3 e SQL parametrizado
    v
PostgreSQL 17 (db :5432)
    |-- servidores
    +-- lotes_importacao
```

O Docker Compose inicia os serviços `db`, `backend` e `frontend`, seus healthchecks e o volume persistente. Nginx serve a interface React e encaminha as requisições `/api/` à API Flask. O aplicativo desktop, executado separadamente, utiliza a mesma URL pública da aplicação.

## Consultas e processamento

O endpoint `GET /api/servidores` recebe nome, cargo, órgão, UF, modo de busca e parâmetros de paginação. Os filtros são combinados por `AND` e as respostas são JSON com `items` e `pagination`.

A validação de parâmetros ocorre na API antes do acesso ao banco. O PostgreSQL utiliza índices B-tree para filtros e ordenação, além de índices GIN com `pg_trgm` para pesquisas por texto e similaridade. A busca por nome utiliza correspondência exata, padrões com `%` ou proximidade textual, conforme o parâmetro fornecido. Os resultados são ordenados e paginados no servidor.

## Importação e integridade

A origem dos registros é identificada por fonte e competência. A importação em lotes normaliza as colunas utilizadas na pesquisa, mantém a origem do registro e evita duplicação por `(fonte, id_origem)`. O campo UF não é inferido quando não está presente na fonte.

Os arquivos de Aposentados e Carreiras/Cargos são descritos em [Fontes dos dados](DATA_SOURCES.md); as rotinas de importação e índices constam em [Banco de dados](DATABASE.md).

## Segurança e limites

As consultas usam parâmetros vinculados no SQL, validação de entradas e limites de paginação. O Nginx aplica limitação de requisições por endereço IP à entrada web. O backend também configura limites de conexão, bloqueio e tempo de consulta.

O Nginx não protege chamadas feitas diretamente à porta publicada do backend; a implantação em ambiente não local deve restringir esse acesso. Consultas amplas ou por similaridade podem exceder o timeout sob concorrência. Os resultados e limitações observados estão em [Desempenho](PERFORMANCE.md).
