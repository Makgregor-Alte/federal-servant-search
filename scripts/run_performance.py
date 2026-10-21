"""Run local load profiles and evaluate Locust CSV statistics."""

import argparse
import csv
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "smoke": ("SmokeUser", 2, 1, 30),
    "baseline": ("SearchUser", 5, 2, 90),
    "overload": ("OverloadUser", 20, 10, 60),
}


def validate_local_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme not in ("http", "https")
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Informe uma URL base local HTTP(S), sem caminho ou credenciais")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Porta HTTP invalida") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Porta HTTP invalida")
    return url.rstrip("/")


def check_api_ready(url, require_data=False):
    """Verify the target is our healthy local application before generating traffic."""
    try:
        with urlopen(url + "/api/health", timeout=5) as resp:
            health = json.loads(resp.read(65536))
            if resp.status != 200 or health.get("status") != "ok" or health.get("database") != "ok":
                raise ValueError("API ou PostgreSQL nao estao prontos")
        with urlopen(url + "/api/servidores?page=1", timeout=10) as resp:
            data = json.loads(resp.read(1048576))
            if resp.status != 200 or not isinstance(data.get("items"), list):
                raise ValueError("Consulta inicial nao respondeu corretamente")
            pagination = data.get("pagination")
            if not isinstance(pagination, dict) or not isinstance(pagination.get("total"), int):
                raise ValueError("Metadados da consulta inicial invalidos")
            total = pagination["total"]
            if require_data and total <= 0:
                raise ValueError("Banco vazio: carregue os dados antes do teste de desempenho")
            return total
    except (URLError, HTTPError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise ValueError("Aplicacao local indisponivel ou com resposta invalida") from exc


def read_stats(csv_file):
    with csv_file.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def evaluate_stats(csv_file, scenario, p95_limit_ms):
    """Assess measured results; 429 is expected only in the overload profile."""
    rows = read_stats(csv_file)
    sample = [row for row in rows if row.get("Name", "").startswith("search/")]
    successful = sum(int(row["Request Count"] or 0) for row in sample if "[200]" in row["Name"])
    limited = sum(int(row["Request Count"] or 0) for row in sample if "[429]" in row["Name"])
    failures = sum(int(row.get("Failure Count") or 0) for row in sample)
    other = sum(int(row["Request Count"] or 0) for row in sample
                if "[200]" not in row["Name"] and "[429]" not in row["Name"])
    aggregate = next((row for row in rows if row.get("Name") == "Aggregated"), None)
    p95 = float(aggregate["95%"] or 0) if aggregate and aggregate.get("95%") else None
    reasons = []
    if not sample or not successful:
        reasons.append("nenhuma consulta HTTP 200 registrada")
    if failures or other:
        reasons.append("existem falhas HTTP ou de contrato")
    if scenario == "overload":
        if not limited:
            reasons.append("limitador HTTP 429 nao foi exercitado")
    else:
        if limited:
            reasons.append("limitador HTTP 429 acionado em carga regular")
        if p95 is None or p95 > p95_limit_ms:
            reasons.append("p95 ausente ou acima do limite")
    return {
        "status": "passed" if not reasons else "failed",
        "successful_requests": successful,
        "rate_limited_requests": limited,
        "failed_requests": failures,
        "other_status_requests": other,
        "p95_all_ms": p95,
        "p95_limit_ms": p95_limit_ms if scenario != "overload" else None,
        "reasons": reasons,
    }


def save_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local HTTP load tests for the search API")
    parser.add_argument("--scenario", choices=tuple(PROFILES), default="smoke")
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--users", type=int, help="Override simulated users")
    parser.add_argument("--spawn-rate", type=float, help="Override users spawned per second")
    parser.add_argument("--seconds", type=int, help="Override duration in seconds")
    parser.add_argument("--p95-ms", type=float, default=2000, help="Maximum p95 in regular profiles")
    parser.add_argument("--require-data", action="store_true", help="Reject an empty database")
    parser.add_argument("--dry-run", action="store_true", help="Show planned execution without requests")
    parser.add_argument("--output", type=Path, help="Report prefix; defaults to test_reports/performance_<scenario>")
    options = parser.parse_args(argv)
    try:
        base_url = validate_local_url(options.url)
    except ValueError as exc:
        parser.error(str(exc))
    user_class, users, spawn, seconds = PROFILES[options.scenario]
    users = options.users if options.users is not None else users
    spawn = options.spawn_rate if options.spawn_rate is not None else spawn
    seconds = options.seconds if options.seconds is not None else seconds
    if not 1 <= users <= 100 or not 0 < spawn <= 100 or not 5 <= seconds <= 600 or not 0 < options.p95_ms <= 60000:
        parser.error("Limites: 1-100 users, spawn rate 0-100, 5-600 seconds, p95 0-60000 ms")
    prefix = options.output or ROOT / "test_reports" / f"performance_{options.scenario}"
    if not prefix.is_absolute():
        prefix = ROOT / prefix
    command = [
        sys.executable, "-m", "locust", "-f", str(ROOT / "scripts" / "locustfile.py"),
        "--headless", "--host", base_url, "--users", str(users),
        "--spawn-rate", str(spawn), "--run-time", f"{seconds}s",
        "--only-summary", "--csv", str(prefix), user_class,
    ]
    if options.dry_run:
        print("Scenario:", options.scenario)
        print("Command:", " ".join(command))
        print("Report:", str(prefix) + "_report.json")
        return 0
    if importlib.util.find_spec("locust") is None:
        print("BLOQUEADO: instale requirements-perf.txt antes de executar o teste", file=sys.stderr)
        return 2
    try:
        total = check_api_ready(base_url, require_data=options.require_data)
    except ValueError as exc:
        print("BLOQUEADO:", str(exc), file=sys.stderr)
        return 2
    prefix.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(command, cwd=ROOT, check=False)
    csv_file = prefix.with_name(prefix.name + "_stats.csv")
    if csv_file.is_file():
        try:
            assessment = evaluate_stats(csv_file, options.scenario, options.p95_ms)
        except (ValueError, KeyError, OSError) as exc:
            assessment = {"status": "failed", "reasons": ["Estatisticas CSV invalidas"], "error_type": type(exc).__name__}
    else:
        assessment = {"status": "failed", "reasons": ["Relatorio CSV do Locust nao foi gerado"]}
    if completed.returncode != 0:
        assessment["status"] = "failed"
        assessment.setdefault("reasons", []).append("Locust encerrou com codigo de erro")
    report = {
        "scenario": options.scenario,
        "status": assessment["status"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_url": base_url,
        "users": users,
        "spawn_rate": spawn,
        "duration_seconds": seconds,
        "database_records_at_start": total,
        "data_requirement_checked": options.require_data,
        "locust_exit_code": completed.returncode,
        "assessment": assessment,
    }
    out_file = prefix.with_name(prefix.name + "_report.json")
    save_report(out_file, report)
    print("Status:", assessment["status"])
    print("Report:", out_file)
    if total == 0:
        print("ATENCAO: banco vazio; desempenho com dados oficiais nao validado")
    return 0 if assessment["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
