# Fontes de dados

## Conjuntos oficiais

| Fonte | Conteúdo | Dicionário | Catálogo |
|---|---|---|---|
| Aposentados | Registros cadastrais de aposentados do Executivo Federal civil | [PDF](https://repositorio.dados.gov.br/segrt/1.20180829-DadosRecursos-Aposentados.pdf) | [dados.gov.br](https://dados.gov.br/dados/conjuntos-dados/gestao-de-pessoas-executivo-federal--aposentados) |
| Carreiras/Cargos | Registros de cargos/empregos ocupados por servidores ativos | [PDF](https://repositorio.dados.gov.br/segrt/2.20190709-DadosRecursos-Carreiras.pdf) | [dados.gov.br](https://dados.gov.br/dados/conjuntos-dados/gestao-de-pessoas-executivo-federal---carreiras--cargos) |

Repositório de arquivos: [Aposentados](https://repositorio.dados.gov.br/segrt/Aposentados/) e [Cargos e Carreiras](https://repositorio.dados.gov.br/segrt/Cargos%20e%20Carreiras/).

## Arquivos de referência (competência maio de 2026)

| Fonte | Arquivo observado no repositório oficial | Uso previsto |
|---|---|---|
| Aposentados | [APOSENTADOS_052026_FULL.csv](https://repositorio.dados.gov.br/segrt/Aposentados/2026/APOSENTADOS_052026_FULL.csv) | Fotografia completa de referência; não misturar indiscriminadamente com arquivos mensais incrementais |
| Carreiras/Cargos | [CARREIRA_052026.txt](https://repositorio.dados.gov.br/segrt/Cargos%20e%20Carreiras/2026/CARREIRA_052026.txt) | Registros de cargos da competência correspondente |

A listagem de aposentados também contém `APOSENTADOS_052026.csv` (menor) e outras competências; a presença de `FULL` no nome indica que é necessário distinguir cargas completas de arquivos incrementais. É necessário verificar a semântica de cada arquivo antes de combinar cargas completas e incrementais. Os arquivos não estão incluídos no repositório de código.

## Campos relevantes para a API

| Campo interno | Aposentados | Carreiras/Cargos |
|---|---|---|
| `nome` | Nome | Nome |
| `cargo` | Cargo | Descrição do Cargo/Emprego |
| `orgao` | Nome do órgão | Denominação do Órgão de atuação |
| `uf` | Não consta no dicionário | UF da UPAG de vinculação |

O campo UF de Carreiras/Cargos refere-se à **unidade pagadora**, e não necessariamente ao estado de residência ou de trabalho. Não será inferida UF para aposentados.

O dicionário de aposentados também descreve CPF mascarado, matrícula, sigla e código do órgão, classe, padrão, referência, nível, tipo e fundamentação da aposentadoria, informações de ingresso, datas e proventos. O de Carreiras/Cargos descreve CPF mascarado, código da carreira, mês de referência e remuneração. Esses campos não são automaticamente incluídos na API.

## Identificação de layout

O diagnóstico identifica separador, codificação, cabeçalhos e quantidade de linhas malformadas em uma amostra. Não importa nem imprime valores dos registros.

```bash
python db/inspect_source.py --source aposentados --file caminho/aposentados.csv
python db/inspect_source.py --source carreiras --file caminho/carreiras.txt
```

Use `--encoding` e `--delimiter` se a identificação automática falhar. Arquivos ZIP precisam ser extraídos antes da inspeção. O diagnóstico retorna um JSON e código de saída 0 quando os campos necessários foram reconhecidos e a amostra não apresenta contagem incorreta de colunas.

A competência 2026-05 foi utilizada nos testes da aplicação. Outros arquivos e competências exigem confrontar os cabeçalhos com os dicionários. A identificação estrita não associa automaticamente cabeçalhos desconhecidos. Não utilizar CPF mascarado, nome ou matrícula isoladamente como identificador único de pessoa sem validar a semântica da fonte.

## Normalização pré-importação

O tratamento lê CSV/TXT sequencialmente, identifica o layout documentado e prepara `nome`, `cargo`, `orgao`, `uf`, `fonte` e `competencia`. Preserva maiúsculas e acentos; limpa espaços e caracteres de controle. Campos de CPF, matrícula e remuneração não são incluídos nos registros destinados à pesquisa. UF ausente ou inválida permanece nula; linhas sem nome ou com número incorreto de colunas são rejeitadas com contagem agregada.

```bash
python db/normalize.py --source aposentados --file caminho/aposentados.csv --max-rows 1000
python db/normalize.py --source carreiras --file caminho/carreiras.txt --max-rows 1000
```

O comando não grava no PostgreSQL nem imprime nomes ou outros valores de pessoas. Saída `0`: nenhuma linha rejeitada; `1`: houve rejeições; `2`: erro de arquivo ou layout. O tratamento já integra a importação do PostgreSQL; para a competência 2026-05, as contagens aceitas/rejeitadas estão apresentadas em `docs/reports/RELATORIO_TECNICO.md`. Não misturar linhas físicas descartadas pelo parsing com registros rejeitados pela importação.
