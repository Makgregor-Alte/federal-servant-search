"""Runtime resource bounds defined in container configuration."""
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class RuntimeConfigTests(unittest.TestCase):
    def test_gunicorn_has_finite_worker_pool_and_timeout(self):
        dockerfile = (ROOT / "backend" / "Dockerfile").read_text()
        command = next(line[4:] for line in dockerfile.splitlines() if line.startswith("CMD "))
        args = json.loads(command)
        self.assertEqual(args[0], "gunicorn")
        self.assertEqual(args[args.index("--workers") + 1], "2")
        self.assertEqual(args[args.index("--threads") + 1], "2")
        self.assertEqual(args[args.index("--timeout") + 1], "20")
        self.assertEqual(args[args.index("--graceful-timeout") + 1], "10")

    def test_nginx_uses_one_rate_limit_zone_for_both_search_routes(self):
        nginx = (ROOT / "frontend" / "nginx.conf").read_text()
        self.assertIn("limit_req_zone $binary_remote_addr zone=servant_queries:10m rate=5r/s;", nginx)
        for route in ("servidores", "servants"):
            self.assertIn(f"location = /api/{route} {{\n        limit_req zone=servant_queries burst=10 nodelay;", nginx)
        self.assertIn("limit_req_status 429;", nginx)
        self.assertIn('"error":"rate_limited"', nginx)
        self.assertIn("location /api/ {", nginx)
        self.assertIn("proxy_read_timeout 15s;", nginx)
        self.assertIn("proxy_connect_timeout 5s;", nginx)

    def test_nginx_does_not_log_query_arguments(self):
        nginx = (ROOT / "frontend" / "nginx.conf").read_text()
        access_format = next(line for line in nginx.splitlines() if line.startswith("log_format safe_access"))
        self.assertIn("$uri", access_format)
        self.assertNotIn("$request_uri", access_format)
        self.assertNotIn("$request ", access_format)
        self.assertNotIn("$args", access_format)


if __name__ == "__main__":
    unittest.main()
