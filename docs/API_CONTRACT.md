# Contrato HTTP da pesquisa

A interface web consulta a API utilizando URLs relativas (`/api/...`). O Nginx encaminha essas requisições ao serviço Flask no Docker Compose. Não é necessário CORS no acesso pelo próprio Nginx.

## Endpoints

| Método | Caminho | Resultado |
| --- | --- | --- |
| GET | `/api/health` | Estado da API e do PostgreSQL |
| GET | `/api/servidores` | Lista paginada de registros |
| GET | `/api/servants` | Alias de `/api/servidores` |

## Parâmetros de pesquisa

| Parâmetro principal | Alias | Observações |
| --- | --- | --- |
| `name` | `nome` | Nome para comparação exata ou aproximada |
| `name_mode` | — | `exact`, `similar` ou `pattern`; padrão `exact` |
| `similar` | — | Alternativa a `name`, interpreta `%` como curinga quando presente |
| `position` | `cargo` | Busca parcial por cargo/profissão |
| `agency` | `orgao` | Busca parcial por órgão/instituição |
| `uf` | — | Sigla das unidades federativas |
| `page` | `pagina` | Página iniciada em 1; padrão 1 |
| `page_size` | `limit` | Registros por página, de 1 a 100; padrão 20 |

Não combine aliases do mesmo parâmetro ou `similar` com `name`/`nome`/`name_mode`. Entradas inválidas geram HTTP 400. A interface envia `similar` quando a opção de nome semelhante inclui `%`, preservando os padrões exigidos pelo enunciado. O formulário permite usar filtros combinados, inclusive pesquisas apenas por cargo, órgão ou UF, sem nome. A interface limita `page_size` às opções 10, 20, 50 e 100 e utiliza os metadados devolvidos pelo banco para navegar entre as páginas.

## Respostas JSON

Pesquisa concluída (HTTP 200):

```json
{
  "items": [
    {"id": 1, "nome": "Nome de exemplo", "cargo": "Cargo", "orgao": "Órgão", "uf": "RS", "fonte": "carreiras"}
  ],
  "pagination": {"page": 1, "page_size": 20, "total": 1, "pages": 1}
}
```

Os campos `cargo`, `orgao` e `uf` podem ser nulos. `items` pode estar vazio e, nesse caso, a primeira página retorna HTTP 200 com `total: 0` e `pages: 0`.

Erro (HTTP 400/503/504/429, conforme o caso):

```json
{"error": "invalid_parameters", "message": "Parâmetros de busca inválidos"}
```

Uma página acima do último resultado retorna HTTP 404 com `error: "page_not_found"`, `items: []` e metadados de paginação. Erros de indisponibilidade ou timeout não incluem credenciais ou detalhes internos.

## Verificação

Testes de montagem das URLs, sem backend ativo:

```bash
cd frontend
npm run test:contract
```

Com a aplicação em execução:

```bash
python scripts/check_runtime.py --contract
```

O verificador HTTP consulta o Nginx, o healthcheck e os modos de busca exata, aproximada e por padrões. Os resultados exibem somente `nome`, `cargo`, `orgao`, `uf` e `fonte`, sem presumir CPF ou outros dados pessoais indisponíveis no contrato. A validade dos dados exibidos depende da importação e da auditoria das fontes oficiais.
