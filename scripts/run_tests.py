"""Run project test suites and write a machine-readable result summary."""

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
OPTIONAL_MODULES = {"flask", "psycopg", "werkzeug"}
DISABLED_IN_UNIT = ("RUN_DB_INTEGRATION_TESTS", "RUN_HTTP_SMOKE_TESTS", "RUN_DB_MAINTENANCE_TESTS")
MISSING_MODULE = re.compile(r"ModuleNotFoundError: No module named ['\"]([\w.]+)['\"]")


def dependency_blocker(exception):
    current = exception
    while current is not None:
        if isinstance(current, ModuleNotFoundError):
            module = (current.name or "").split(".")[0]
            if module in OPTIONAL_MODULES:
                return module
        current = current.__cause__ or current.__context__
    # unittest wraps failures during test-module discovery in ImportError.
    if isinstance(exception, ImportError) and "Failed to import test module:" in str(exception):
        match = MISSING_MODULE.search(str(exception))
        if match and match.group(1).split(".")[0] in OPTIONAL_MODULES:
            return match.group(1).split(".")[0]
    return None


class ClassifiedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.blocked = []

    def addError(self, test, err):
        module = dependency_blocker(err[1])
        if module is not None:
            self.blocked.append({"test": test.id(), "dependency": module})
            self.addSkip(test, f"dependency unavailable: {module}")
        else:
            super().addError(test, err)


def summarize(result):
    blocked_count = len(result.blocked)
    skipped = len(result.skipped) - blocked_count
    failures = len(result.failures)
    errors = len(result.errors)
    expected = len(result.expectedFailures)
    unexpected = len(result.unexpectedSuccesses)
    passed = result.testsRun - blocked_count - skipped - failures - errors - expected - unexpected
    if failures or errors or unexpected:
        status = "failed"
    elif blocked_count:
        status = "blocked"
    else:
        status = "passed"
    return {
        "status": status,
        "total": result.testsRun,
        "passed": passed,
        "skipped": skipped,
        "blocked": blocked_count,
        "failures": failures,
        "errors": errors,
        "expected_failures": expected,
        "unexpected_successes": unexpected,
        "blocked_dependencies": dict(sorted(Counter(b["dependency"] for b in result.blocked).items())),
        "blocked_tests": result.blocked,
        "failed_tests": [test.id() for test, _ in result.failures + result.errors],
    }


@contextmanager
def isolated_unit_environment():
    previous = {name: os.environ.pop(name, None) for name in DISABLED_IN_UNIT}
    original_path = list(sys.path)
    sys.path.insert(0, str(ROOT / "backend"))
    try:
        yield
    finally:
        sys.path[:] = original_path
        for name, value in previous.items():
            if value is not None:
                os.environ[name] = value


def run_unit():
    with isolated_unit_environment():
        suite = unittest.TestLoader().discover(
            str(ROOT / "backend" / "tests"), pattern="test_*.py",
            top_level_dir=str(ROOT / "backend" / "tests"),
        )
        result = unittest.TextTestRunner(
            verbosity=1, resultclass=ClassifiedResult, stream=sys.stderr,
        ).run(suite)
    return summarize(result)


def run_integration():
    missing = []
    if not shutil.which("docker"):
        missing.append("Docker CLI")
    if not (ROOT / ".env").is_file():
        missing.append(".env")
    if missing:
        return {"status": "blocked", "prerequisites": missing, "exit_code": None}
    try:
        completed = subprocess.run([sys.executable, str(ROOT / "scripts" / "test_backend.py")], cwd=ROOT, check=False)
    except OSError as error:
        return {"status": "blocked", "prerequisites": [type(error).__name__], "exit_code": None}
    return {"status": "passed" if completed.returncode == 0 else "failed", "exit_code": completed.returncode}


def save_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the project's automated test suites")
    parser.add_argument("--suite", choices=("unit", "integration", "all"), default="unit")
    parser.add_argument("--report", type=Path, help="JSON report output path")
    options = parser.parse_args(argv)
    started = time.monotonic()
    suites = {}
    if options.suite in ("unit", "all"):
        suites["unit"] = run_unit()
    if options.suite in ("integration", "all"):
        suites["integration"] = run_integration()
    statuses = [s["status"] for s in suites.values()]
    status = "failed" if "failed" in statuses else "blocked" if "blocked" in statuses else "passed"
    report = {
        "suite": options.suite,
        "status": status,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_seconds": round(time.monotonic() - started, 3),
        "suites": suites,
    }
    output = options.report or ROOT / "test_reports" / f"tests_{options.suite}.json"
    if not output.is_absolute():
        output = ROOT / output
    save_report(output, report)
    for name, result in suites.items():
        counts = " ".join(f"{key}={result[key]}" for key in ("total", "passed", "skipped", "blocked", "failures", "errors") if key in result)
        print(f"{name.upper()}: {result['status']} {counts}".rstrip())
        if result.get("prerequisites"):
            print("  Missing prerequisites: " + ", ".join(result["prerequisites"]))
    print(f"Report: {output}")
    return {"passed": 0, "failed": 1, "blocked": 2}[status]


if __name__ == "__main__":
    raise SystemExit(main())
