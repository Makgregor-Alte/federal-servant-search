# Integração INT-01 / DB-01 / BE-01 — 10/10/2026

Este código foi integrado **localmente** a partir do ZIP `federal-servant-search-frontend-react.zip` e do pacote preliminar. Não está publicado no GitHub. A branch original do Yuri foi preservada integralmente em `frontend/` (nenhum arquivo anterior dessa pasta foi modificado).

## Componentes

- `db`: PostgreSQL 17, extensão `pg_trgm`, tabela `servidores`, índices e volume persistente.
- `backend`: Flask + Gunicorn, validação de filtros, paginação, buscas por nome/cargo/órgão/UF.
- `frontend`: build com Node/Vite; Nginx serve os arquivos estáticos e encaminha `/api` ao serviço backend.
- `.github/workflows/ci.yml`: testes Python, verificação TS/lint/build do frontend e validação Compose após push/PR.

## Inicialização no Windows (PowerShell)

1. Copie `.env.example` para `.env` e altere `POSTGRES_PASSWORD` (arquivo `.env` é ignorado pelo Git).
2. Execute `docker compose config` e depois `docker compose up --build -d`.
3. Confira `docker compose ps`, `docker compose logs --tail=100 backend`.
4. Acesse `http://localhost:8080`, `http://localhost:8080/api/health` e `http://localhost:8080/api/servidores?page=1`.
5. O banco começa vazio. `items: []` é resultado esperado antes da importação.

**Não validamos o Docker neste ambiente:** é obrigatório rodar os passos acima antes de aceitar a integração. Sem dataset real, não há busca de nomes para verificar.

## API

- `GET /api/health` — `{ "status":"ok", "database":"ok" }` ou HTTP 503.
- `GET /api/servidores` — alias `/api/servants`.
- Parâmetros opcionais: `name`, `name_mode` (`exact`/`similar`), `position`, `agency`, `uf`, `page` (>=1) e `page_size` (1–100).
- Resposta: `{"items":[{"id":1,"nome":"...","cargo":"...","orgao":"...","uf":"RS","fonte":"carreira"}],"pagination":{"page":1,"page_size":20,"total":1,"pages":1}}`.
- Erros HTTP 400 para filtros inválidos; 503 para falhas de acesso ao PostgreSQL.
- O servidor usa **queries parametrizadas** (evitam injeção SQL). Similaridade implementada com `pg_trgm`.

## Importar amostra do dataset oficial

No PC host, crie ambiente Python com `psycopg[binary]` e defina `PGHOST=localhost`, `PGPORT=5432`, `PGDATABASE=federal_servants`, `PGUSER=app_user` e `PGPASSWORD=<senha-do-.env>`. Em PowerShell, por exemplo: `$env:PGHOST='localhost'`, etc.

Valide o CSV antes de inserir:

```powershell
python db/import_csv.py --file .\data\raw\carreira.csv --source carreira --name-column NOME --position-column CARGO --agency-column ORGAO --uf-column UF --delimiter ';' --encoding utf-8-sig --limit 1000 --dry-run
```

Após conferir cabeçalhos, separador e encoding reais, execute novamente sem `--dry-run`. As opções `--position-column`, `--agency-column`, `--uf-column` e `--id-column` são opcionais. Os dados não devem ser presumidos: na base de aposentados a UF pode não existir; importá-la como NULL, sem inferência.

**Importante:** a pasta `db/` original estava vazia. O esquema SQL incluído é uma **proposta de modelo**, ainda não mapeada para os CSVs oficiais do projeto. Dados importados permanecem em volume Docker, não versionar CSVs com dados pessoais.

## Preservação de dados

O script `db/01_schema.sql` é executado automaticamente apenas no primeiro bootstrap do volume do PostgreSQL. Mudanças futuras devem ser aplicadas por migração; evite `docker compose down -v` para não destruir dados.

## Integração com o frontend do Yuri

O código original renderiza apenas a tela de cadastro, e `frontend/src/components/Login/Login.tsx` está vazio. Cadastro ainda não comunica com backend e inclui um `console.log` de senha, que **deve ser removido antes de disponibilizar o cadastro para usuários reais**. Esse código foi preservado sem modificação por autoria e para não interferir na FE-01. O frontend de pesquisa continua pendente de implementação e integração na FE-01.

Para a tela de pesquisa, o Yuri poderá chamar `fetch('/api/servidores?name=Maria&name_mode=similar&uf=RS&page=1')` e renderizar loading, erro e resultados vazios.

## Branches e pushes automáticos

1. No clone Git real: `git fetch origin`, `git switch -c feat/integration origin/frontend/react`.
2. Extraia os arquivos **deste ZIP** numa pasta temporária e copie o conteúdo para a raiz do clone, sem substituir `.git`. Compare `git diff`, `git status`.
3. Execute `PYTHONPATH=backend python -m unittest discover -s backend/tests -v` em Git Bash, ou `$env:PYTHONPATH='backend'; python -m unittest discover -s backend/tests -v` no PowerShell.
4. Instale hooks **opcionalmente**: `powershell -ExecutionPolicy Bypass -File .\scripts\install-hooks.ps1`.
5. Faça um commit **explícito** após revisar mudanças: `git add ...; git commit -m 'feat(integration): configura API, banco e compose'`. O hook `post-commit` faz push automaticamente apenas em branches `feat/*`, `fix/*` ou `integration/*`, nunca em `main` ou `frontend/react`.
6. Desative o hook com `git config --local --unset core.hooksPath`. Desative um push específico com variável `GIT_AUTO_PUSH=0` no ambiente do terminal.
7. Abra Pull Request para `main` quando CI e Docker estiverem verificados.

O ZIP baixado do GitHub **não inclui o diretório `.git`**, por isso nenhum script consegue publicar commits diretamente a partir dele. Nunca usar commits artificiais para preencher histórico; cada alteração representa trabalho efetivamente realizado.

## Limitações de validação

- Testes unitários Python disponíveis e sintaxe dos arquivos foram verificados localmente.
- Build/lint TypeScript do frontend dependem de `npm ci`: dependências não puderam ser instaladas neste ambiente; GitHub Actions fará esses checks após push.
- Docker Engine não disponível nesta sessão: compose foi validado apenas quanto ao YAML e referências, não executado.
- Critérios integrais das Issues ainda precisam ser conferidos no GitHub.
