# Testes de desempenho e proteção contra sobrecarga

Os testes foram realizados por HTTP através do Nginx, em uma instalação com 1.497.448 registros das fontes oficiais de maio de 2026. Os resultados originais estão em [`reports/anexos_http/`](reports/anexos_http/).

## Resultados

| Ensaio | Carga | Resultado | Medida de tempo |
|---|---|---|---|
| Funcional | 92 verificações sequenciais | 92 aprovadas | p95 de 991,93 ms |
| Carga moderada | 40 requisições, 2 trabalhadores, até 3 req/s | 40 HTTP 200 | p95 de 40,72 ms |
| Rajada | 80 requisições, 8 trabalhadores | 11 HTTP 200; 69 HTTP 429 | p95 agregado de 73,21 ms |
| Similaridade concorrente | 4 pesquisas simultâneas, 2 trabalhadores | 4 HTTP 504 | aproximadamente 6,0–6,1 s por requisição |

Cada ensaio de carga inclui uma verificação de saúde adicional, que respondeu HTTP 200. A bateria funcional verifica nome, cargo, órgão, todas as UFs, combinações, paginação, padrões com `%`, entradas inválidas e respostas de erro.

O limitador do Nginx foi configurado para 5 requisições por segundo por IP, com rajada de 10. Durante o teste de rajada, o servidor respondeu HTTP 429 às solicitações que excederam o limite. O p95 dessa bateria inclui respostas 429 rápidas e não representa isoladamente a latência das pesquisas aceitas.

## Reproduzir os testes

Com a aplicação e os dados importados, a partir de `projeto/`:

```bash
python scripts/test_api_exhaustive.py --url http://127.0.0.1:8080 --mode functional --require-data
python scripts/test_api_exhaustive.py --url http://127.0.0.1:8080 --mode steady --require-data --confirm-load
python scripts/test_api_exhaustive.py --url http://127.0.0.1:8080 --mode burst --require-data --confirm-load
```

Para testes adicionais com Locust, instale `requirements-perf.txt` e utilize `scripts/run_performance.py`; os cenários estão definidos em `scripts/performance_scenarios.py` e `scripts/locustfile.py`.

## Limitações

A contagem exata de resultados pode aumentar o tempo de consultas amplas e da paginação profunda. Uma pesquisa sem filtros chegou a retornar HTTP 504 em 3.058,7 ms; em execução posterior, a mesma modalidade respondeu dentro do limite. Em um ensaio separado, quatro buscas por similaridade concorrentes retornaram HTTP 504, apesar de o endpoint de saúde permanecer disponível. Esses casos estão registrados nos arquivos `falha_inicial_sem_filtros.json` e `falha_fuzzy_concorrente.json`.

O backend utiliza Gunicorn com 2 workers e 2 threads por worker. O timeout SQL é de 3 s para pesquisas comuns e 6 s para similaridade. A limitação de requisições opera na entrada Nginx; acessos diretos à porta Flask não passam por ela.

A carga moderada e a rajada exercitam requisições diferentes das consultas fuzzy de maior custo. Assim, a aprovação desses dois perfis não elimina os timeouts observados sob similaridade concorrente. Medidas de latência também variam com concorrência, disco, cache e recursos da máquina.
