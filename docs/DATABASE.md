# Banco de dados e importação

O Federal Servant Search utiliza PostgreSQL 17 e a extensão `pg_trgm` para consultar dados públicos do Poder Executivo Federal. Os scripts de esquema, integridade e índices ficam na pasta `db/`.

## Modelo

| Tabela | Finalidade |
|---|---|
| `servidores` | Registros consultáveis, incluindo nome, cargo, órgão, UF, fonte, identificador de origem e competência. |
| `lotes_importacao` | Controle de arquivos processados, competência, hash SHA-256, situação e contagens de importação. |

A chave `(fonte, id_origem)` impede reinserir uma mesma linha de origem. Ela não identifica uma pessoa de maneira universal: nomes iguais e vínculos diferentes podem representar registros distintos. O campo `uf` permanece nulo quando essa informação não existe na fonte, como ocorre em Aposentados.

## Esquema e índices

Na primeira inicialização de um volume PostgreSQL, o Docker executa, em ordem:

1. `db/01_schema.sql` — tabelas principais.
2. `db/02_model.sql` — competência e controle dos lotes.
3. `db/03_integrity.sql` — restrições de integridade.
4. `db/04_indexes.sql` — índices para as consultas.

Para iniciar uma instalação nova, na raiz `projeto/`:

```bash
docker compose up --build
```

O banco novo inicia com a estrutura, mas sem os arquivos de dados oficiais. Volumes já existentes não executam novamente os scripts de inicialização. Nesses casos, as migrações podem ser aplicadas com `python scripts/db_maintenance.py migrate`, após configurar o ambiente e realizar backup. A opção `docker compose down -v` exclui o volume PostgreSQL e não deve ser utilizada para atualizar o esquema.

### Índices utilizados

| Índice | Tipo | Uso |
|---|---|---|
| `idx_servidores_nome_ordenacao` | B-tree em `(LOWER(nome), id)` | Nome exato e ordenação |
| `idx_servidores_uf_nome` | B-tree em `(uf, LOWER(nome), id)` | Pesquisa por UF |
| `idx_servidores_nome_similar` | GIN com `gin_trgm_ops` | Similaridade e padrões de nome |
| `idx_servidores_cargo` | GIN com `gin_trgm_ops` | Busca parcial por cargo |
| `idx_servidores_orgao` | GIN com `gin_trgm_ops` | Busca parcial por órgão |

Após uma importação extensa, as estatísticas podem ser atualizadas com:

```bash
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "ANALYZE servidores;"'
```

O script `db/profile_indexes.py` utiliza `EXPLAIN (ANALYZE, BUFFERS)` para avaliar planos e tempos das consultas. A utilização efetiva dos índices depende da seletividade dos filtros e do tamanho da base.

## Fontes oficiais

Foram utilizados os arquivos de maio de 2026, de acordo com os dicionários descritos em [Fontes de dados](DATA_SOURCES.md):

| Conjunto | Arquivo |
|---|---|
| Aposentados | `APOSENTADOS_052026_FULL.csv` |
| Carreiras/Cargos | `CARREIRA_052026.txt` |

O arquivo de aposentados indicado é o conjunto completo (`FULL`), diferente do arquivo incremental do mesmo mês. Os dois arquivos devem ser extraídos em uma pasta fora do repositório, por exemplo `../dados-oficiais`. Os arquivos oficiais não fazem parte do ZIP do projeto.

O leitor reconhece diferenças de separador, codificação e cabeçalhos. Registros inválidos são contabilizados, e as linhas físicas descartadas durante a recuperação de CSV malformado são medidas separadamente dos registros rejeitados. A leitura tem limites de tamanho e de quantidade de linhas físicas por registro para impedir que um registro incompleto consuma o restante do arquivo.

## Preparação e importação

O script `scripts/prepare_official_data.py` reúne inspeção, validação e importação dos dois conjuntos da mesma competência. Os comandos a seguir são executados na raiz `projeto/`, com Python 3 e Docker Compose instalados.

**1. Conferir cabeçalhos, competência e arquivos:**

```bash
python scripts/prepare_official_data.py --data-dir ../dados-oficiais --competencia 2026-05
```

**2. Validar todos os registros, sem gravar no banco:**

```bash
docker compose build backend
python scripts/prepare_official_data.py --data-dir ../dados-oficiais --competencia 2026-05 --mode validate
```

**3. Importar após a validação:**

```bash
docker compose up -d db
python scripts/prepare_official_data.py --data-dir ../dados-oficiais --competencia 2026-05 --mode import --confirm
```

A importação completa é feita por lotes com `COPY` e `ON CONFLICT (fonte, id_origem) DO NOTHING`. O tamanho padrão de lote é de 1.000 registros. O processo controla proveniência e evita reinserir registros idênticos do mesmo arquivo em reexecuções.

A importação interrompe a gravação por padrão quando encontra erros estruturais. Se a validação integral encontrar registros malformados, é necessário revisar as contagens antes de utilizar `db/import_bulk.py` por fonte, com `--max-structural-errors` explicitamente ajustado. Não altere os arquivos oficiais para suprimir rejeições.

A importação de uma competência diferente exige verificar a correspondência entre os dois conjuntos e seus dicionários. A ferramenta não combina automaticamente arquivos completos com incrementais nem identifica uma mesma pessoa entre competências distintas.

### Importação de amostra

`db/import_sample.py` permite validar ou importar amostras de 100, 1.000 ou 10.000 linhas. Sem `--apply`, o script apenas verifica o arquivo. Para testar a importação em um banco separado, utilize `--apply` e confira a competência antes de gravar.

`db/import_bulk.py` aceita `--file`, `--source` (`aposentados` ou `carreiras`), `--competencia`, `--batch-size`, `--max-rows` e `--apply`. Esses comandos permitem tratar cada fonte separadamente quando necessário.

## Verificar os resultados

Após importar os dois conjuntos, examine as contagens no PostgreSQL:

```bash
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT fonte, COUNT(*) FROM servidores GROUP BY fonte;"'
```

E consulte os lotes mais recentes:

```bash
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT id, fonte, estado, linhas_lidas, linhas_importadas, linhas_descartadas FROM lotes_importacao ORDER BY id DESC LIMIT 10;"'
```

A execução com os arquivos de maio/2026 resultou em 1.085.301 registros de Carreiras/Cargos e 412.147 de Aposentados, totalizando 1.497.448 registros. Foram rejeitados 132 registros na importação (2 de Carreiras/Cargos e 130 de Aposentados). A recuperação do arquivo de Aposentados descartou ainda 207 linhas físicas, contagem diferente daquela de registros rejeitados.

Para verificar índices e integridade, estão disponíveis `db/audit_integrity.py`, `scripts/validate_database.py` e `scripts/check_runtime.py`. As respostas da API devem ser confrontadas com os totais efetivamente importados.

## Backups e manutenção

O script `scripts/db_maintenance.py` permite criar e verificar backups, aplicar migrações e testar restaurações em bancos separados:

```bash
python scripts/db_maintenance.py backup
python scripts/db_maintenance.py migrate
```

Para restauração, utilize `restore --file CAMINHO_DO_BACKUP --database sii_restore_verificacao --confirm` somente em um banco de destino separado. O script não substitui a base principal. As operações de manutenção exigem conexão Docker ativa e podem interromper consultas; backups e arquivos de dados devem permanecer fora do repositório.

Os testes de integração com PostgreSQL devem ser executados em um ambiente de testes independente, pois podem criar ou alterar estruturas de teste. O fluxo de CI está descrito em [Execução e integração](INTEGRATION_GUIDE.md).
