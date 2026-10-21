"""HTTP contract for cargo/profissão search without a live database."""
import unittest
from unittest.mock import patch

from app import create_app
class FakeCursor:
    def __init__(self, queries, count, rows):
        self.queries = queries
        self.count = count
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchone(self):
        return {"count": self.count}

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, queries, count, rows):
        self.fake_cursor = FakeCursor(queries, count, rows)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self.fake_cursor


class PositionHttpTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.testing = True
        self.client = app.test_client()
        self.queries = []

    def test_cargo_alias_and_json_response(self):
        rows = [{"id": 10, "nome": "Ana", "cargo": "Analista", "orgao": "FURG", "uf": "RS", "fonte": "carreira"}]
        with patch("app.routes.connect_db", return_value=FakeConnection(self.queries, count=1, rows=rows)):
            result = self.client.get("/api/servidores?cargo=analista")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["items"], rows)
        self.assertEqual(result.json["pagination"]["total"], 1)
        self.assertEqual(self.queries[0][1]["position"], "%analista%")
        self.assertIn("cargo ILIKE %(position)s", self.queries[0][0])

    def test_nonexistent_job_returns_empty_list(self):
        with patch("app.routes.connect_db", return_value=FakeConnection(self.queries, count=0, rows=[])):
            result = self.client.get("/api/servidores?cargo=naoexiste123")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["items"], [])
        self.assertEqual(result.json["pagination"]["total"], 0)

    def test_empty_cargo_is_400_without_database_access(self):
        with patch("app.routes.connect_db") as db:
            for query in ("cargo=", "cargo=%20%20", "position="):
                with self.subTest(query=query):
                    result = self.client.get("/api/servidores?" + query)
                    self.assertEqual(result.status_code, 400)
                    self.assertEqual(result.json["error"], "invalid_parameters")
            db.assert_not_called()

    def test_sql_injection_stays_in_parameter(self):
        with patch("app.routes.connect_db", return_value=FakeConnection(self.queries, count=0, rows=[])):
            result = self.client.get("/api/servidores", query_string={"cargo": "Analista' OR TRUE --"})
        self.assertEqual(result.status_code, 200)
        self.assertNotIn("OR TRUE", self.queries[0][0])
        self.assertEqual(self.queries[0][1]["position"], "%Analista' OR TRUE --%")


if __name__ == "__main__":
    unittest.main()
