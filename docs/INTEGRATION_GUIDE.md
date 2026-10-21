# Execução, integração e testes

## Inicialização

Com Docker Compose, a partir da pasta `projeto/`:

```bash
docker compose up --build
```

O Compose inicia PostgreSQL, API Flask/Gunicorn e Nginx. O frontend fica em `http://localhost:8080/sistema`; os serviços backend e banco utilizam as portas internas 5000 e 5432. Para alterar portas e credenciais, consulte `.env.example`.

Os arquivos SQL `db/01_schema.sql` a `db/04_indexes.sql` são aplicados automaticamente ao criar um volume PostgreSQL novo. A base é inicialmente vazia. A importação dos dados oficiais é descrita em [Banco de dados](DATABASE.md).

Em volumes que já existiam antes de alterações no esquema, as migrações podem ser executadas por `python scripts/db_maintenance.py migrate`, após criar backup. Não é necessário recriar o volume para atualizar os arquivos do aplicativo.

## API e frontend

O Nginx encaminha `/api/*` para o Flask. A rota de pesquisa é `GET /api/servidores`, com parâmetros de nome, similaridade, cargo, órgão, UF e paginação. O frontend utiliza os módulos `src/api/query.js` e `src/api/servidores.js` para montar requisições e validar respostas.

O aplicativo desktop reutiliza o mesmo contrato HTTP e é executado fora do Docker. Consulte [Desktop](../desktop/README.md).

## Verificações

```bash
python scripts/check_runtime.py --url http://127.0.0.1:8080 --contract
python scripts/run_tests.py --suite unit
```

Testes de integração com um PostgreSQL real podem criar e modificar esquemas de testes; devem ser executados em um ambiente Docker separado do banco com dados oficiais. O teste automatizado utilizado pelo CI está em `scripts/test_backend.py`.

Testes do frontend:

```bash
cd frontend
npm ci
npm run test:contract
npx tsc --noEmit
npm run lint
npm run build
```

A integração automática do GitHub Actions valida Python, TypeScript, frontend, Compose e os testes de integração num ambiente próprio. Consulte `.github/workflows/ci.yml`.

## Testes de carga

O script `scripts/test_api_exhaustive.py` reúne verificações da API e perfis de carga. Para metodologia, resultados e limitações, consulte [Desempenho](PERFORMANCE.md).
