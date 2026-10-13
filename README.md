# Federal Servant Search

Aplicação full-stack de pesquisa de registros públicos de servidores federais brasileiros.

## Arquitetura

```text
Browser --HTTP--> Nginx (React/Vite) --/api/--> Flask + Gunicorn --> PostgreSQL
                                                           (pg_trgm)
```

## Funcionalidades de API disponíveis

- Busca exata e por similaridade de nome (`pg_trgm`)
- Filtros de cargo, órgão e UF, combináveis
- Paginação e respostas JSON
- Validação de parâmetros e SQL parametrizado
- Healthcheck da API e conexão com banco
- Importador CSV configurável para amostras de datasets oficiais

**Estado atual:** frontend do Yuri preservado (cadastro parcial, sem autenticação real; login pendente); tela de pesquisa e dados oficiais ainda não integrados. Este é um pacote de integração preliminar, ainda não validado em Docker real.

## Desenvolvimento

```powershell
Copy-Item .env.example .env
# Edite POSTGRES_PASSWORD em .env
docker compose config
docker compose up --build -d
```

Frontend: `http://localhost:8080`; API: `http://localhost:8080/api/servidores` e `http://localhost:8080/api/health`.

Consulte [docs/INTEGRATION_GUIDE.md](docs/INTEGRATION_GUIDE.md) para filtros, importação de dados, segurança, testes e hooks Git.

## Estrutura

- `backend/`: API REST Flask + Gunicorn e testes Python.
- `db/`: esquema PostgreSQL e importador CSV.
- `frontend/`: React/Vite e configuração Nginx (código do Yuri preservado).
- `docs/`: documentação de integração e acompanhamento.
- `.github/workflows/ci.yml`: CI automático para PRs e pushes.
- `.githooks/`: verificações e push automatizado com instalação voluntária.

## Colaboração

Equipe de quatro integrantes. Desenvolvimento em branches com Pull Requests e histórico de commits real. Não há commits ou pushes produzidos por este pacote.
