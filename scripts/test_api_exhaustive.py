#!/usr/bin/env python3
"""Read-only, bounded HTTP contract and load diagnostics for Federal Servant Search.

Python standard library only. Calls the frontend/Nginx URL, never the database.
Targets loopback only; never accepts a remote hostname. Use --mode all --confirm-load
for sequential checks + bounded concurrency; --mode functional alone is gentler.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

TEST_NAME = "NOME_INEXISTENTE_PARA_TESTE"
UF_CODES = "AC AL AP AM BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split()


@dataclass
class Result:
    label: str
    phase: str
    status: int | None
    duration_ms: float
    passed: bool
    detail: str = ""


def base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError("Porta HTTP invalida") from error
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or not parsed.netloc or parsed.username or parsed.password
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or port is not None and not (1 <= port <= 65535)):
        raise ValueError("Use apenas uma URL HTTP local, ex.: http://127.0.0.1:8080")
    return value


def request(base: str, path: str, params=None, *, timeout=12, method="GET"):
    if params:
        path += "?" + urlencode(params, doseq=True)
    started = time.perf_counter()
    req = Request(base + path, method=method,
                  headers={"Accept": "application/json, text/html"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            status, headers, content = resp.status, resp.headers, resp.read(2_000_001)
    except HTTPError as error:
        status, headers, content = error.code, error.headers, error.read(2_000_001)
    except (URLError, TimeoutError, ConnectionError, OSError) as error:
        return None, None, round((time.perf_counter() - started) * 1000, 2), type(error).__name__
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    if len(content) > 2_000_000:
        return status, None, elapsed, "response_too_large"
    content_type = headers.get("Content-Type", "").lower()
    if path == "/" and "text/html" in content_type:
        return status, {"html": "<html" in content.decode("utf-8", errors="replace").lower()}, elapsed, ""
    if "application/json" not in content_type:
        return status, None, elapsed, "not_json"
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return status, None, elapsed, "invalid_json"
    return status, payload, elapsed, ""


def assert_page(payload, page, size):
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("items ausentes ou invalidos")
    pagination = payload.get("pagination")
    if not isinstance(pagination, dict):
        raise ValueError("pagination ausente")
    for key in ("page", "page_size", "total", "pages"):
        value = pagination.get(key)
        if type(value) is not int or value < 0:
            raise ValueError(f"pagination.{key} invalido")
    if (pagination["page"] != page or pagination["page_size"] != size
            or pagination["pages"] != ceil(pagination["total"] / size)):
        raise ValueError("metadados de paginacao incoerentes")
    if len(payload["items"]) > size or len(payload["items"]) > pagination["total"]:
        raise ValueError("numero de itens incoerente")
    ids = set()
    for item in payload["items"]:
        if not isinstance(item, dict) or type(item.get("id")) is not int:
            raise ValueError("id invalido")
        if item["id"] in ids:
            raise ValueError("id duplicado na pagina")
        ids.add(item["id"])
        if not isinstance(item.get("nome"), str):
            raise ValueError("nome invalido")
        for field in ("cargo", "orgao", "uf", "fonte"):
            if field not in item or item[field] is not None and not isinstance(item[field], str):
                raise ValueError(f"campo {field} invalido")
    if pagination["total"] > 0 and page <= pagination["pages"] and not payload["items"]:
        raise ValueError("pagina existente retornou vazia")
    return payload["items"], pagination


def percentile(numbers, pct):
    if not numbers:
        return None
    ordered = sorted(numbers)
    index = (len(ordered) - 1) * pct
    lo, hi = int(index), min(int(index) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo), 2)


class Suite:
    def __init__(self, base, timeout, pause, verbose=False):
        self.base, self.timeout, self.pause, self.verbose = base, timeout, pause, verbose
        self.results = []
        self.data_total = None
        self.context = {}
        self.last_result = None

    def check(self, label, params=None, *, status_expected=200, page=None, size=None,
              verify=None, path="/api/servidores", method="GET", phase="functional"):
        if self.results:
            time.sleep(self.pause)
        status, payload, duration, issue = request(self.base, path, params, timeout=self.timeout, method=method)
        detail = issue
        passed = status == status_expected and not issue
        if not passed and not detail:
            detail = f"HTTP {status}, esperado {status_expected}"
        if passed:
            try:
                if path == "/":
                    if not payload or not payload.get("html"):
                        raise ValueError("HTML nao encontrado")
                elif status_expected == 200 and path == "/api/health":
                    if not isinstance(payload, dict) or payload.get("status") != "ok" or payload.get("database") != "ok":
                        raise ValueError("health sem status=ok e database=ok")
                elif status_expected == 200:
                    items, metadata = assert_page(payload, page or 1, size or 20)
                    if verify:
                        verify(items, metadata)
                elif status_expected == 400:
                    if not isinstance(payload, dict) or payload.get("error") != "invalid_parameters":
                        raise ValueError("HTTP 400 sem error=invalid_parameters")
                elif status_expected == 404 and path.startswith("/api/servidores"):
                    if not isinstance(payload, dict) or payload.get("error") != "page_not_found":
                        raise ValueError("HTTP 404 sem error=page_not_found")
                elif status_expected in {404, 405}:
                    if not isinstance(payload, dict) or "error" not in payload:
                        raise ValueError("resposta de erro sem contrato JSON")
            except (TypeError, KeyError, ValueError) as error:
                passed, detail = False, str(error)
        outcome = Result(label, phase, status, duration, passed, detail)
        self.results.append(outcome)
        self.last_result = payload if passed else None
        print(f"{'PASSOU' if passed else 'FALHOU':6} {label:46.46s} HTTP {str(status):>4}  {duration:8.1f}ms" + (f"  {detail}" if detail else ""), flush=True)
        return payload if passed else None

    def functional(self, require_data):
        self.check("frontend HTML", path="/", status_expected=200)
        self.check("health + PostgreSQL", path="/api/health", status_expected=200)
        payload = self.check("sem filtros / paginacao padrao", page=1, size=20)
        unrestricted_ok = payload is not None
        if payload is None:
            # A global COUNT(*) may time out on the full official dataset. Record
            # that failure, but still exercise independent routes and validations.
            # No global total is inferred from the restricted sample.
            payload = self.check("amostra restrita para prosseguir: UF AC",
                                 {"uf": "AC", "page_size": 20}, page=1, size=20)
            self.context["global_total_unverified"] = True
        if payload is not None:
            items, metadata = assert_page(payload, 1, 20)
            if unrestricted_ok:
                self.data_total = metadata["total"]
            self.context["sample_filter"] = "unrestricted" if unrestricted_ok else "uf=AC"
        else:
            items, metadata = [], {"total": 0, "pages": 0}
            self.context["sample_filter"] = "none"
        if require_data and not items and (self.data_total is None or self.data_total == 0):
            self.results.append(Result("base oficial sem amostra comprovada", "readiness", None, 0.0, False,
                                       "buscas de amostra falharam; total oficial nao verificado"))
            print("AVISO: nao foi possivel confirmar a presenca de dados; so verificacoes independentes prosseguirao.")
        first = next((x for x in items if x["nome"].strip()), None)
        # Most queries below are generated from a real row, rather than assuming
        # any particular employee name is available in the official dataset.
        sample_name = first["nome"] if first else None
        sample_position = next((x["cargo"] for x in items if x["cargo"]), None)
        sample_agency = next((x["orgao"] for x in items if x["orgao"]), None)
        sample_uf = next((x["uf"] for x in items if x["uf"]), None)
        self.context["sample"] = bool(sample_name)
        self.context["database_records"] = self.data_total

        if unrestricted_ok:
            if self.data_total > 20:
                self.check("sem filtros / pagina 2", {"page": 2, "page_size": 20}, page=2, size=20,
                           verify=lambda rows, meta: self._disjoint(rows, items))
            for sz in (1, 10, 50, 100):
                self.check(f"limite e pagina: {sz}", {"page_size": sz}, size=sz)
            self.check("aliases pagina/limit", {"pagina": 1, "limit": 10}, size=10)
        else:
            print("PULADO: 6 casos sem filtro para nao repetir COUNT(*) custoso; falha-base registrada.")
            self.context["unrestricted_cases_skipped"] = 6
        self.check("pagina 1 sem correspondencia", {"nome": TEST_NAME, "page_size": 10}, size=10,
                   verify=lambda rows, meta: self._expect_zero(rows, meta))
        self.check("busca exata inexistente SQL injection inofensiva",
                   {"nome": "x' OR 1=1 --", "page_size": 10}, size=10,
                   verify=lambda rows, meta: self._expect_zero(rows, meta))
        if sample_name:
            self.check("nome exato existente", {"name": sample_name, "name_mode": "exact", "page_size": 10},
                       size=10, verify=lambda rows, meta: self._matching_name(rows, meta, sample_name))
            self.check("alias nome exato", {"nome": sample_name, "page_size": 10},
                       size=10, verify=lambda rows, meta: self._matching_name(rows, meta, sample_name))
            self.check("nome exato sem diferenciar maiusculas", {"name": sample_name.swapcase(), "page_size": 10},
                       size=10, verify=lambda rows, meta: self._matching_name(rows, meta, sample_name))
        if sample_position:
            token = sample_position[:min(10, len(sample_position))]
            self.check("cargo / profession", {"cargo": token, "page_size": 10}, size=10,
                       verify=lambda rows, meta: self._containing(rows, "cargo", token))
            self.check("alias position", {"position": token, "page_size": 10}, size=10,
                       verify=lambda rows, meta: self._containing(rows, "cargo", token))
        if sample_agency:
            token = sample_agency[:min(12, len(sample_agency))]
            self.check("orgao / agency", {"orgao": token, "page_size": 10}, size=10,
                       verify=lambda rows, meta: self._containing(rows, "orgao", token))
            self.check("alias agency", {"agency": token, "page_size": 10}, size=10,
                       verify=lambda rows, meta: self._containing(rows, "orgao", token))
        uf_resp = self.check("UF RS", {"uf": "RS", "page_size": 10}, size=10,
                             verify=lambda rows, meta: self._only_uf(rows, "RS"))
        # Cover every accepted state abbreviation in the source API.
        for uf in UF_CODES:
            if uf != "RS":
                self.check(f"UF valida {uf}", {"uf": uf, "page_size": 5}, size=5,
                           verify=lambda rows, meta, current=uf: self._only_uf(rows, current))
        if uf_resp:
            for row in uf_resp["items"]:
                if row["uf"] and row["cargo"] and row["orgao"]:
                    sample_uf = row["uf"]
                    self.check("combinacao cargo + UF", {"cargo": row["cargo"][:10], "uf": sample_uf, "page_size": 10},
                               size=10, verify=lambda rows, meta: self._only_uf(rows, sample_uf))
                    self.check("combinacao orgao + UF", {"orgao": row["orgao"][:12], "uf": sample_uf, "page_size": 10},
                               size=10, verify=lambda rows, meta: self._only_uf(rows, sample_uf))
                    self.check("combinacao nome + cargo + UF",
                               {"nome": row["nome"], "cargo": row["cargo"][:10], "uf": sample_uf, "page_size": 10},
                               size=10, verify=lambda rows, meta: self._only_uf(rows, sample_uf))
                    break
        if sample_name:
            # Page-not-found uses a restrictive name filter, avoiding huge OFFSET scans.
            limited = self.check("consultar paginacao de nome exato",
                                 {"name": sample_name, "page_size": 10}, size=10)
            if limited:
                missing_page = limited["pagination"]["pages"] + 1
                if missing_page <= 1_000_000:
                    self.check("pagina inexistente: HTTP 404",
                               {"name": sample_name, "page_size": 10, "page": missing_page},
                               status_expected=404)
        # Representative expensive modes: run each ONCE, with explicit latency tracking.
        self.check("similaridade: Mariana (trigramas)",
                   {"name": "Mariana", "name_mode": "similar", "page_size": 10}, size=10)
        self.check("similar=Mariana (alias)", {"similar": "Mariana", "limit": 10}, size=10)
        self.check("padrao Mariana% (prefixo)",
                   {"name": "Mariana%", "name_mode": "pattern", "page_size": 10}, size=10)
        self.check("padrao %maria (sufixo): caso caro",
                   {"name": "%maria", "name_mode": "pattern", "page_size": 10}, size=10)
        self.check("similar com % interpreta padrao",
                   {"similar": "Mariana%", "limit": 10}, size=10)
        if sample_name and len(sample_name.split()) >= 2:
            words = sample_name.split()
            first_token, last_token = words[0], words[-1]
            for label, value in (
                ("padrao NOME%SOBRENOME%", f"{first_token}%{last_token}%"),
                ("padrao NOME SOBRENOME%", f"{first_token} {last_token}%"),
                ("padrao NOME%SOBRENOME", f"{first_token}%{last_token}"),
                ("padrao %NOME%SOBRENOME%", f"%{first_token}%{last_token}%"),
            ):
                self.check(label, {"name": value, "name_mode": "pattern", "page_size": 10}, size=10)
        # Negative cases validate no DB work for invalid requests.
        invalid_cases = [
            ("UF invalida ZZ", {"uf": "ZZ"}),
            ("UF invalida 1", {"uf": "1"}),
            ("UF invalida SQL injection", {"uf": "RS';DROP TABLE servidores;--"}),
            ("nome vazio", {"nome": ""}),
            ("cargo vazio", {"cargo": ""}),
            ("orgao vazio", {"orgao": ""}),
            ("UF vazia", {"uf": ""}),
            ("nome grande demais", {"name": "A" * 151}),
            ("cargo grande demais", {"position": "A" * 151}),
            ("modo inexistente", {"name": "X", "name_mode": "fuzzy"}),
            ("modo sem nome", {"name_mode": "similar"}),
            ("padrao apenas wildcard", {"name": "%%%", "name_mode": "pattern"}),
            ("pagina zero", {"page": 0}),
            ("pagina negativa", {"page": -1}),
            ("pagina nao numerica", {"page": "abc"}),
            ("pagina decimal", {"page": "1.5"}),
            ("pagina alem do teto", {"page": 1_000_001}),
            ("page_size zero", {"page_size": 0}),
            ("page_size 101", {"page_size": 101}),
            ("page_size decimal", {"page_size": "1.2"}),
            ("page_size negativo", {"page_size": -20}),
            ("parametro desconhecido", {"unknown": "X"}),
            ("alias name/nome conflitantes", {"name": "Maria", "nome": "Maria"}),
            ("alias cargo/position conflitantes", {"cargo": "X", "position": "X"}),
            ("alias orgao/agency conflitantes", {"orgao": "X", "agency": "X"}),
            ("alias limit/page_size conflitantes", {"limit": 10, "page_size": 10}),
            ("name/similar conflitantes", {"name": "Maria", "similar": "Maria"}),
            ("name repetido", [("name", "Maria"), ("name", "Joao")]),
            ("UF repetida", [("uf", "RS"), ("uf", "SC")]),
            ("controle no nome", {"name": "Maria\nAna"}),
        ]
        for label, params in invalid_cases:
            self.check(label, params, status_expected=400)
        self.check("metodo POST rejeitado", method="POST", status_expected=405)
        self.check("endpoint inexistente", path="/api/rota-inexistente", status_expected=404)
        self.check("saude depois das consultas", path="/api/health", status_expected=200)
        # Never initiate stress tests after any failing functional request.
        # A restricted sample does not validate the official global total.
        return (unrestricted_ok and self.data_total is not None
                and (not require_data or self.data_total > 0)
                and all(result.passed for result in self.results))

    @staticmethod
    def _disjoint(rows, previous):
        if {row["id"] for row in rows} & {row["id"] for row in previous}:
            raise ValueError("ids repetidos nas paginas 1 e 2")

    @staticmethod
    def _expect_zero(rows, meta):
        if rows or meta["total"] != 0:
            raise ValueError("busca inexistente encontrou registros")

    @staticmethod
    def _matching_name(rows, meta, name):
        if meta["total"] < 1 or not rows or any(row["nome"].casefold() != name.casefold() for row in rows):
            raise ValueError("nome exato nao corresponde ao registro de referencia")

    @staticmethod
    def _only_uf(rows, uf):
        if any(row["uf"] != uf for row in rows):
            raise ValueError("filtro UF nao foi aplicado")

    @staticmethod
    def _containing(rows, key, value):
        if any(value.casefold() not in (row[key] or "").casefold() for row in rows):
            raise ValueError("filtro textual nao foi aplicado")

    def load(self, phase, *, workers, count, rps=None, expensive=False):
        # Readiness check is mandatory for any extra traffic and is kept out of the load statistics.
        code, payload, elapsed, error = request(self.base, "/api/health", timeout=self.timeout)
        if code != 200 or error or not isinstance(payload, dict) or payload.get("status") != "ok":
            outcome = Result("readiness " + phase, phase, code, elapsed, False, error or "health falhou")
            self.results.append(outcome)
            print(f"FALHOU readiness {phase}: {outcome.detail}")
            return
        print(f"\nCarga {phase}: {count} requisicoes, {workers} trabalhadores" + (f", teto ~{rps} req/s" if rps else ""), flush=True)
        time.sleep(2.0)  # allow Nginx's per-IP burst tokens to recover
        params = ({"name": "Mariana", "name_mode": "similar", "page_size": 10}
                  if expensive else {"name": TEST_NAME, "page_size": 10})
        tasks = []
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for i in range(count):
                if rps:
                    due = started + i / rps
                    delay = due - time.perf_counter()
                    if delay > 0:
                        time.sleep(delay)
                tasks.append(executor.submit(request, self.base, "/api/servidores", params, timeout=self.timeout))
            for future in as_completed(tasks):
                status, body, latency, issue = future.result()
                try:
                    if issue:
                        raise ValueError(issue)
                    if status == 200:
                        rows, meta = assert_page(body, 1, 10)
                        if not expensive:
                            self._expect_zero(rows, meta)
                    elif status == 429 and phase == "burst":
                        if not isinstance(body, dict) or body.get("error") != "rate_limited":
                            raise ValueError("HTTP 429 sem contrato rate_limited")
                    else:
                        raise ValueError(f"HTTP {status} inesperado")
                except (TypeError, ValueError, KeyError) as error:
                    self.results.append(Result(phase, phase, status, latency, False, str(error)))
                else:
                    self.results.append(Result(phase, phase, status, latency, True))
        elapsed = round(time.perf_counter() - started, 2)
        batch = [x for x in self.results if x.phase == phase]
        counts = Counter(str(x.status) for x in batch)
        ok = sum(x.passed for x in batch)
        print(f"Carga {phase}: {ok}/{len(batch)} aceitas pelo contrato | HTTP {dict(counts)} | {elapsed}s", flush=True)
        self.check("health apos carga " + phase, path="/api/health", status_expected=200, phase=phase)
        if phase == "burst" and 429 not in {x.status for x in batch}:
            self.results.append(Result("limiter respondeu 429", phase, None, 0, False,
                                       "limitador nao foi exercitado; repetir em ambiente controlado"))


def summarize(results):
    phases = sorted({result.phase for result in results})
    output = {}
    for phase in phases:
        batch = [result for result in results if result.phase == phase]
        duration = [result.duration_ms for result in batch if result.status is not None]
        output[phase] = {
            "requests": len(batch), "passed": sum(x.passed for x in batch),
            "failed": sum(not x.passed for x in batch),
            "http_statuses": dict(Counter(str(x.status) for x in batch)),
            "p50_ms": percentile(duration, 0.5), "p95_ms": percentile(duration, 0.95),
            "max_ms": max(duration) if duration else None,
        }
    return output


def generate_markdown(report):
    lines = ["# Auditoria HTTP - Federal Servant Search", "",
             f"Data (UTC): {report['generated_at_utc']}", "",
             f"Alvo local: `{report['base_url']}`", "",
             f"Registros na origem: {report['database_records'] if report['database_records'] is not None else 'NAO VERIFICADO'}", "",
             f"Contexto da amostra: {report.get('context', {})}", "",
             "**Método:** GETs e POST rejeitado por rota somente-leitura; sem SQL direto, importação ou modificação de dados.", "",
             "## Resumo", "",
             "| Fase | Requisições | Passaram | Falharam | p95 (ms) | HTTP |", "|---|---:|---:|---:|---:|---|"]
    for phase, summary in report["summary"].items():
        lines.append(f"| {phase} | {summary['requests']} | {summary['passed']} | {summary['failed']} | {summary['p95_ms']} | {summary['http_statuses']} |")
    lines.extend(["", "## Falhas", ""])
    fails = [row for row in report["results"] if not row["passed"]]
    if fails:
        for result in fails:
            lines.append(f"- **{result['phase']} / {result['label']}**: HTTP {result['status']}, {result['duration_ms']} ms; {result['detail']}")
    else:
        lines.append("Nenhuma falha nesta execução (não é prova de ausência de falhas em outras cargas).")
    lines.extend(["", "## Limitações e interpretação", "",
                  "- O modo `pattern` com `%` inicial pode retornar HTTP 504 por custo do SQL; isso é falha funcional/limite de desempenho, não resultado aprovado.",
                  "- O HTTP 429 é esperado *somente* durante o perfil `burst`, como evidência do rate limiting (5 req/s/IP e burst 10 no Nginx).",
                  "- O p95 de `burst` inclui respostas 429 rápidas e **não** mede a latência das consultas HTTP 200 isoladamente.",
                  "- A duração de cada consulta, hardware, cache do PostgreSQL e população dos dados influenciam o resultado.",
                  "- Resultados de `fuzzy` concorrente são diagnósticos dirigidos, não uma garantia de capacidade sustentada.",
                  "- As buscas são somente-leitura, mas cargas podem afetar outras pessoas que estiverem usando o computador.",
                  "- Se a busca geral falhar, os casos globais dependentes dela serao pulados; os erros serao mantidos no relatorio e nenhuma carga adicional sera iniciada.",
                  "- Não substituir resultados não executados por evidência histórica. Este arquivo reflete apenas a execução registrada.", ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Auditoria de pesquisa HTTP e carga limitada (somente localhost, read-only)")
    parser.add_argument("--url", default="http://127.0.0.1:8080", help="URL do frontend Nginx, nao a porta da API direta")
    parser.add_argument("--mode", choices=("functional", "steady", "burst", "fuzzy", "all"), default="functional")
    parser.add_argument("--timeout", type=float, default=12.0, help="Limite por requisicao (8 a 30 s)")
    parser.add_argument("--pause", type=float, default=0.3, help="Intervalo entre casos funcionais (minimo 0.2 s)")
    parser.add_argument("--require-data", action="store_true", help="Exige dados carregados para teste com dados oficiais")
    parser.add_argument("--confirm-load", action="store_true", help="Confirma execucao de carga sobre o computador local")
    parser.add_argument("--output", default="test_reports/api_exhaustive", help="Prefixo dos relatorios JSON/Markdown")
    args = parser.parse_args(argv)
    try:
        args.url = base_url(args.url)
    except ValueError as error:
        parser.error(str(error))
    if not (8 <= args.timeout <= 30) or not (0.2 <= args.pause <= 5.0):
        parser.error("--timeout deve ser 8-30 s e --pause 0.2-5.0 s")
    if args.mode in {"steady", "burst", "fuzzy", "all"} and not args.confirm_load:
        parser.error("Perfis de carga precisam de --confirm-load (execucao local deliberada)")
    suite = Suite(args.url, args.timeout, args.pause)
    if args.mode in {"functional", "all"}:
        ready = suite.functional(args.require_data)
    else:
        code, health, _, issue = request(args.url, "/api/health", timeout=args.timeout)
        code2, baseline, _, issue2 = request(args.url, "/api/servidores", {"page_size": 10}, timeout=args.timeout)
        ready = bool(code == 200 and not issue and isinstance(health, dict) and health.get("status") == "ok"
                     and code2 == 200 and not issue2 and isinstance(baseline, dict))
        if ready:
            try:
                _, pg = assert_page(baseline, 1, 10)
                suite.data_total = pg["total"]
                if args.require_data and suite.data_total == 0:
                    ready = False
            except (TypeError, ValueError):
                ready = False
        if not ready:
            suite.results.append(Result("readiness API + dados", "readiness", None, 0, False,
                                        "banco ausente, vazio ou API indisponivel"))
            print("BLOQUEADO: readiness falhou; nenhuma carga sera disparada.")
    if not ready and args.mode == "all":
        print("SEM TESTE DE CARGA: existem falhas funcionais. O relatorio registrou os resultados restantes.", flush=True)
    if ready:
        if args.mode in {"steady", "all"}:
            suite.load("steady", workers=2, count=40, rps=3)
        if args.mode in {"burst", "all"}:
            suite.load("burst", workers=8, count=80)
        if args.mode == "fuzzy":
            suite.load("fuzzy", workers=2, count=4, expensive=True)
    output = Path(args.output)
    if output.suffix in {".json", ".md"}:
        parser.error("--output deve ser prefixo, sem extensao")
    output.parent.mkdir(parents=True, exist_ok=True)
    results = [asdict(result) for result in suite.results]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_url": args.url,
        "mode": args.mode,
        "database_records": suite.data_total,
        "context": suite.context,
        "status": "PASSED" if results and all(x["passed"] for x in results) and ready else "FAILED",
        "summary": summarize(suite.results),
        "results": results,
    }
    json_file = output.with_suffix(".json")
    md_file = output.with_suffix(".md")
    json_file.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_file.write_text(generate_markdown(report), encoding="utf-8")
    print("\nRESUMO:", report["status"], "|", report["summary"], flush=True)
    print("Relatorios:", json_file, "|", md_file, flush=True)
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
