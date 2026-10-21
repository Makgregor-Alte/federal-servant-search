# Federal Servant Search

Sistema de consulta pública de servidores ativos e aposentados do Poder Executivo Federal. Oferece pesquisa por nome exato, similaridade, padrões com `%`, cargo, órgão e unidade federativa, com filtros combinados, paginação e detalhes dos resultados.

## Tecnologias e estrutura

| Componente | Tecnologia |
|---|---|
| Banco de dados | PostgreSQL 17, `pg_trgm`, índices B-tree e GIN |
| API | Python 3.12, Flask, Gunicorn e Psycopg 3 |
| Interface web | React, TypeScript, Vite e Nginx |
| Aplicativo desktop | Python, Tkinter e cliente HTTP; executável Windows |
| Execução | Docker Compose com três serviços (`db`, `backend`, `frontend`) |

O frontend consulta a API Flask por meio do proxy Nginx. A versão desktop utiliza a mesma API e funciona fora dos contêineres.

## Executar o sistema

É necessário ter Docker e Docker Compose instalados. Na pasta `projeto/`:

```bash
docker compose up --build
```

A interface fica em [http://localhost:8080/sistema](http://localhost:8080/sistema) e a API em `/api/servidores`. As portas padrão são 8080 (web), 5000 (API) e 5432 (PostgreSQL), publicadas apenas no computador local. É possível alterá-las com `WEB_PORT`, `API_PORT` e `POSTGRES_PORT` em um arquivo `.env`, a partir de `.env.example`.

A senha padrão do Compose é destinada exclusivamente à execução local. Ao instalar em outro ambiente, configure `POSTGRES_PASSWORD` antes da criação do volume. Não publique o serviço com a credencial de demonstração.

O banco inicia com o esquema e os índices, mas **sem os dados oficiais**. A importação é uma etapa separada: consulte [Banco de dados](docs/DATABASE.md) e [Fontes oficiais](docs/DATA_SOURCES.md). Os conjuntos de dados e o volume PostgreSQL não integram esta distribuição.

Uma verificação HTTP básica pode ser executada após a inicialização:

```bash
python scripts/check_runtime.py --url http://127.0.0.1:8080 --contract
```

Para consultar resultados reais, importe primeiro os arquivos oficiais. O volume do PostgreSQL persiste entre reinicializações comuns dos contêineres.

## Aplicativo desktop

O código está em `desktop/`. No Windows, o executável compilado acompanha o projeto em `desktop/release/FederalServantSearch.exe`; ele utiliza o backend em funcionamento e não contém os dados localmente. A URL padrão é `http://127.0.0.1:8080`.

Também é possível executar o código-fonte:

```bash
python desktop/main.py
```

Veja [instruções do desktop](desktop/README.md) para uso, testes e compilação.

## Documentação

- [Arquitetura](docs/ARCHITECTURE.md) — serviços e fluxo das requisições
- [API](docs/API_CONTRACT.md) — parâmetros de busca e respostas JSON
- [Banco de dados](docs/DATABASE.md) — esquema, importação e índices
- [Fontes dos dados](docs/DATA_SOURCES.md) — proveniência e campos disponíveis
- [Execução e integração](docs/INTEGRATION_GUIDE.md) — desenvolvimento e testes
- [Desempenho](docs/PERFORMANCE.md) — medições de carga e limitações
- [Relatório técnico](docs/reports/RELATORIO_TECNICO.md) — desenvolvimento, equipe e resultados

O sistema não exige login para consultar os dados. As páginas `/login` e `/cadastro` apenas encaminham o visitante à pesquisa pública; não há criação de contas ou armazenamento de credenciais.
