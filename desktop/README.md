# Federal Servant Search — Desktop

Aplicativo gráfico em Python e Tkinter para consultar a API Flask do Federal Servant Search. Oferece busca por nome exato, similaridade e padrões com `%`, além de filtros por cargo, órgão, UF, paginação e visualização dos registros encontrados.

O cliente desktop não acessa o PostgreSQL diretamente. É necessário manter a API em execução para realizar pesquisas.

## Executar

O executável Windows compilado acompanha a distribuição:

```text
desktop/release/FederalServantSearch.exe
```

Também é possível utilizar Python 3 com Tkinter:

```bash
python desktop/main.py
```

Na interface, informe a URL da aplicação, por padrão `http://127.0.0.1:8080`, escolha os filtros e selecione **Pesquisar**. Uma URL diferente pode ser utilizada quando `WEB_PORT` estiver configurada no Compose.

## Compilar no Windows

Na pasta `desktop/`, com Python 3 instalado, execute no PowerShell:

```powershell
.\build_windows.ps1
```

O script utiliza PyInstaller para criar o executável em `dist/` e copiá-lo para `release/`. O binário distribuído foi gerado em Windows; para recompilá-lo é necessário o ambiente Windows. O executável não contém os dados nem inicia o backend.

## Testes do cliente

Na pasta `desktop/`:

```bash
python -m unittest discover -s tests -v
```

Os testes verificam a montagem das requisições, interpretação de respostas HTTP e erros, usando respostas simuladas.
