"""Flask endpoint/contract tests without a live database or network."""
import os
import unittest
from unittest.mock import patch

import psycopg

from app import create_app


class FakeCursor:
    def __init__(self, statement_log, count=2, rows=None):
        self.log = statement_log
        self.count = count
        self.rows = rows or []
        self.last_sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.log.append((sql, params))
        self.last_sql = sql

    def fetchone(self):
        return {"count": self.count}

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, statement_log, count=2, rows=None):
        self.cursor_obj = FakeCursor(statement_log, count, rows)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self.cursor_obj


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()
        self.log = []
        self.rows = [
            {"id": 11, "nome": "Maria da Silva", "cargo": "Analista", "orgao": "FURG", "uf": "RS", "fonte": "carreira"},
            {"id": 12, "nome": "Mariana Souza", "cargo": "Tecnica", "orgao": "UFPEL", "uf": "RS", "fonte": "carreira"},
        ]

    def fake_db(self, **_options):
        return FakeConnection(self.log, count=len(self.rows), rows=self.rows)

    def test_health_checks_connection(self):
        with patch("app.routes.connect_db", side_effect=self.fake_db):
            result = self.client.get("/api/health")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json, {"status": "ok", "database": "ok"})
        self.assertIn("SELECT 1", self.log[0][0])

    def test_health_reports_unavailable_database(self):
        with patch("app.routes.connect_db", side_effect=psycopg.OperationalError("offline")):
            result = self.client.get("/api/health")
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json["database"], "unavailable")

    def test_http_search_contract(self):
        with patch("app.routes.connect_db", side_effect=self.fake_db):
            result = self.client.get("/api/servidores?name=Maria&name_mode=similar&uf=RS&page=1&page_size=5")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json["items"]), 2)
        self.assertEqual(result.json["pagination"], {"page": 1, "page_size": 5, "total": 2, "pages": 1})
        self.assertIn("%", self.log[1][1]["name_pattern"])
        self.assertEqual(self.log[1][1]["uf"], "RS")

    def test_alias_route_and_empty_response(self):
        with patch("app.routes.connect_db", return_value=FakeConnection(self.log, count=0, rows=[])):
            result = self.client.get("/api/servants")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["items"], [])
        self.assertEqual(result.json["pagination"]["pages"], 0)

    def test_invalid_parameters_are_400_without_db_access(self):
        with patch("app.routes.connect_db") as db:
            for query in ("page=0", "uf=XX", "name_mode=bad", "page_size=101"):
                with self.subTest(query=query):
                    result = self.client.get("/api/servidores?" + query)
                    self.assertEqual(result.status_code, 400)
                    self.assertEqual(result.json["error"], "invalid_parameters")
            db.assert_not_called()

    def test_db_failure_is_503_and_never_exposes_credentials(self):
        with patch("app.routes.connect_db", side_effect=psycopg.OperationalError("secret-password")):
            result = self.client.get("/api/servidores")
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json["error"], "database_unavailable")
        self.assertNotIn("secret-password", result.get_data(as_text=True))

    def test_api_404_is_json(self):
        result = self.client.get("/api/rota-inexistente")
        self.assertEqual(result.status_code, 404)
        self.assertEqual(result.json["error"], "http_error")

    def test_cors_is_allowlisted(self):
        with patch.dict(os.environ, {"ALLOWED_ORIGINS": "http://localhost:5173"}):
            allowed = self.client.get("/api/rota-inexistente", headers={"Origin": "http://localhost:5173"})
            denied = self.client.get("/api/rota-inexistente", headers={"Origin": "https://example.com"})
        self.assertEqual(allowed.headers.get("Access-Control-Allow-Origin"), "http://localhost:5173")
        self.assertIsNone(denied.headers.get("Access-Control-Allow-Origin"))


if __name__ == "__main__":
    unittest.main()
