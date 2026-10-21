# Frontend

Interface React com TypeScript e Vite, servida pelo Nginx na instalação Docker. A consulta principal está em `/sistema`; a raiz redireciona para essa rota. `/login` e `/cadastro` são páginas informativas, sem autenticação ou coleta de senhas.

## Desenvolvimento local

```sh
npm ci
npm run test:contract
npx tsc --noEmit
npm run lint
npm run build
npm run dev
```

O desenvolvimento local usa o proxy de `/api` configurado no Vite, com o Flask disponível na porta 5000. No Docker Compose, o Nginx publica a porta definida por `WEB_PORT` na raiz do projeto (padrão `8080`) e encaminha `/api/` ao backend.

A interface consulta `GET /api/servidores`. O módulo `src/api/query.js` monta os filtros; `src/api/servidores.js` valida as respostas. A API realiza a paginação e o frontend apresenta estados de carregamento, lista vazia, erro e limite de requisições.
