"""Offline tests of the local load runner and Locust report parsing."""

import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from run_performance import evaluate_stats, check_api_ready, save_report, validate_local_url


class RunnerTests(unittest.TestCase):
    def test_only_local_target_is_allowed(self):
        for url in ("http://localhost:8080", "http://127.0.0.1:5000", "http://[::1]:8080"):
            self.assertEqual(validate_local_url(url), url)
        for url in ("https://example.com", "http://127.0.0.1:8080/api", "http://localhost/?x=1", "http://name:password@localhost", "file:///tmp", "http://localhost:abc"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_local_url(url)

    def test_dry_run_requires_no_external_dependency(self):
        with TemporaryDirectory() as folder:
            command = [sys.executable, str(ROOT / "scripts/run_performance.py"),
                       "--scenario", "overload", "--dry-run", "--output", str(Path(folder) / "test")]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("OverloadUser", completed.stdout)
            self.assertFalse(list(Path(folder).iterdir()))

    def test_input_limits_are_enforced(self):
        for args in (("--users", "0"), ("--seconds", "601"), ("--spawn-rate", "0"), ("--p95-ms", "0")):
            completed = subprocess.run([sys.executable, str(ROOT / "scripts/run_performance.py"), "--dry-run", *args],
                                       capture_output=True, text=True, check=False)
            with self.subTest(args=args):
                self.assertNotEqual(completed.returncode, 0)

    def write_sample(self, folder, entries):
        path = Path(folder) / "perf_stats.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["Type", "Name", "Request Count", "Failure Count", "95%"])
            writer.writeheader()
            for name, count, failures, p95 in entries:
                writer.writerow({"Type": "GET", "Name": name, "Request Count": count, "Failure Count": failures, "95%": p95})
        return path

    def test_smoke_passes_only_without_failures(self):
        with TemporaryDirectory() as folder:
            stats = self.write_sample(folder, [("search/exact [200]", 12, 0, 130), ("Aggregated", 12, 0, 130)])
            self.assertEqual(evaluate_stats(stats, "smoke", 2000)["status"], "passed")
            stats = self.write_sample(folder, [("search/exact [200]", 12, 0, 4000), ("Aggregated", 12, 0, 4000)])
            self.assertEqual(evaluate_stats(stats, "baseline", 2000)["status"], "failed")

    def test_overload_requires_429_and_rejects_5xx(self):
        with TemporaryDirectory() as folder:
            stats = self.write_sample(folder, [("search/exact [200]", 12, 0, 500), ("search/exact [429]", 25, 0, 50), ("Aggregated", 37, 0, 350)])
            evaluation = evaluate_stats(stats, "overload", 2000)
            self.assertEqual(evaluation["status"], "passed")
            self.assertEqual(evaluation["rate_limited_requests"], 25)
            stats = self.write_sample(folder, [("search/exact [200]", 12, 0, 500), ("search/exact [503]", 2, 2, 50), ("search/exact [429]", 25, 0, 50), ("Aggregated", 39, 2, 350)])
            self.assertEqual(evaluate_stats(stats, "overload", 2000)["status"], "failed")
            stats = self.write_sample(folder, [("search/exact [200]", 12, 0, 500), ("Aggregated", 12, 0, 500)])
            self.assertEqual(evaluate_stats(stats, "overload", 2000)["status"], "failed")

    def test_regular_profile_rejects_rate_limit(self):
        with TemporaryDirectory() as folder:
            stats = self.write_sample(folder, [("search/exact [200]", 12, 0, 120), ("search/exact [429]", 3, 3, 10), ("Aggregated", 15, 3, 110)])
            self.assertEqual(evaluate_stats(stats, "baseline", 2000)["status"], "failed")

    def test_save_report_atomic(self):
        with TemporaryDirectory() as folder:
            target = Path(folder) / "nested" / "report.json"
            save_report(target, {"status": "passed"})
            self.assertEqual(json.loads(target.read_text())["status"], "passed")
            self.assertFalse(target.with_name("report.json.tmp").exists())

    def test_check_api_ready_with_local_http_server(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/api/health":
                    data = {"status": "ok", "database": "ok"}
                else:
                    data = {"items": [], "pagination": {"page": 1, "page_size": 20, "total": 0, "pages": 0}}
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            self.assertEqual(check_api_ready(url), 0)
            with self.assertRaises(ValueError):
                check_api_ready(url, require_data=True)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
