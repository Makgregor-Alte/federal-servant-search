"""Contrato de inicialização dos serviços e verificação HTTP de execução."""

import importlib.util
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check_runtime.py"
SPEC = importlib.util.spec_from_file_location("check_runtime", SCRIPT)
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


class ComposeRuntimeTests(unittest.TestCase):
    def test_postgres_health_requires_schema_and_migrations(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("pg_trgm", compose)
        self.assertIn("lotes_importacao", compose)
        self.assertIn("servidores_id_origem_preenchido_ck", compose)
        self.assertIn("grep -qx t", compose)
        self.assertIn('PGPASSWORD="$$POSTGRES_PASSWORD"', compose)
        self.assertIn('test:', compose)

    def test_backend_and_frontend_use_health_gates(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("condition: service_healthy", compose)
        self.assertIn("urllib.request.urlopen('http://127.0.0.1:5000/api/health'", compose)
        self.assertIn("wget -q -O /dev/null http://127.0.0.1/", compose)
        self.assertIn("postgres_data:/var/lib/postgresql/data", compose)
        self.assertNotIn("docker compose down -v", compose)


class HttpRuntimeTests(unittest.TestCase):
    @staticmethod
    def responses(total=0):
        return [
            (200, "text/html; charset=utf-8", b"<!doctype html><html><head></head></html>"),
            (200, "application/json", json.dumps({"status": "ok", "database": "ok"}).encode()),
            (200, "application/json", json.dumps({
                "items": [], "pagination": {"page": 1, "page_size": 20, "total": total, "pages": 0}
            }).encode()),
            (400, "application/json", b'{"error":"invalid_parameters"}'),
        ]

    def test_empty_database_is_not_an_http_failure(self):
        with patch.object(RUNTIME, "request", side_effect=self.responses()):
            self.assertEqual(RUNTIME.check()["total_records"], 0)

    def test_valid_nonempty_database(self):
        with patch.object(RUNTIME, "request", side_effect=self.responses(total=30)):
            self.assertEqual(RUNTIME.check()["checks"], 4)

    def test_health_degraded_fails(self):
        values = self.responses()
        values[1] = (503, "application/json", b'{"status":"degraded","database":"unavailable"}')
        with patch.object(RUNTIME, "request", side_effect=values):
            with self.assertRaisesRegex(RUNTIME.RuntimeCheckError, "HTTP 503"):
                RUNTIME.check()

    def test_wrong_pagination_contract_fails(self):
        values = self.responses()
        values[2] = (200, "application/json", b'{"items":[],"pagination":{"page":1}}')
        with patch.object(RUNTIME, "request", side_effect=values):
            with self.assertRaisesRegex(RUNTIME.RuntimeCheckError, "paginação inválido"):
                RUNTIME.check()

    def test_invalid_uf_requires_json_400(self):
        values = self.responses()
        values[3] = (200, "application/json", b"{}")
        with patch.object(RUNTIME, "request", side_effect=values):
            with self.assertRaisesRegex(RUNTIME.RuntimeCheckError, "HTTP 200"):
                RUNTIME.check()


    def test_http_smoke_against_local_http_server(self):
        payloads = {
            "/": (200, "text/html", b"<!doctype html><html><body>app</body></html>"),
            "/api/health": (200, "application/json", b'{"status":"ok","database":"ok"}'),
            "/api/servidores?page=1": (200, "application/json",
                b'{"items":[],"pagination":{"page":1,"page_size":20,"total":0,"pages":0}}'),
            "/api/servidores?uf=ZZ": (400, "application/json", b'{"error":"invalid_parameters"}'),
        }

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                status, content_type, data = payloads.get(self.path, (404, "text/plain", b"not found"))
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            self.assertEqual(RUNTIME.check(url)["checks"], 4)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_invalid_base_url_is_rejected(self):
        with self.assertRaises(RUNTIME.RuntimeCheckError):
            RUNTIME.check("file:///etc/passwd")
        with self.assertRaises(RUNTIME.RuntimeCheckError):
            RUNTIME.check("http://alice:password@localhost:8080")


if __name__ == "__main__":
    unittest.main()
