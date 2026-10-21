"""HTTP contract for searches by institution or agency."""
import unittest
from unittest.mock import patch

from app import create_app


class FakeCursor:
    def __init__(self, queries, rows):
        self.queries = queries
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchone(self):
        return {"count": len(self.rows)}

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, queries, rows):
        self.fake_cursor = FakeCursor(queries, rows)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self.fake_cursor


class AgencyHttpTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.testing = True
        self.client = app.test_client()
        self.queries = []

    def test_portuguese_alias_returns_json(self):
        rows = [{"id": 9, "nome": "Ana", "cargo": "Analista", "orgao": "Universidade Federal", "uf": "RS", "fonte": "carreira"}]
        with patch("app.routes.connect_db", return_value=FakeConnection(self.queries, rows)):
            response = self.client.get("/api/servidores?orgao=universidade")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["items"], rows)
        self.assertEqual(response.json["pagination"]["total"], 1)
        self.assertEqual(self.queries[0][1]["agency"], "%universidade%")
        self.assertIn("orgao ILIKE %(agency)s", self.queries[0][0])

    def test_existing_frontend_parameter_and_combination(self):
        with patch("app.routes.connect_db", return_value=FakeConnection(self.queries, [])):
            response = self.client.get("/api/servidores?agency=FURG&cargo=Analista&uf=RS")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["items"], [])
        self.assertEqual(response.json["pagination"]["pages"], 0)
        self.assertEqual(self.queries[0][1]["agency"], "%FURG%")
        self.assertEqual(self.queries[0][1]["position"], "%Analista%")
        self.assertEqual(self.queries[0][1]["uf"], "RS")

    def test_invalid_organization_is_400_without_database_access(self):
        with patch("app.routes.connect_db") as db:
            for query in (
                "orgao=", "orgao=%20%20", "agency=", "orgao=FURG&agency=FURG",
                "orgao=FURG&orgao=IFRS", "orgao=FURG%00", "orgao=FURG%0AIFRS",
            ):
                with self.subTest(query=query):
                    response = self.client.get("/api/servidores?" + query)
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json["error"], "invalid_parameters")
            db.assert_not_called()

    def test_sql_injection_passes_only_as_parameter(self):
        with patch("app.routes.connect_db", return_value=FakeConnection(self.queries, [])):
            response = self.client.get("/api/servidores", query_string={"orgao": "FURG' OR TRUE --"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(" OR TRUE", self.queries[0][0])
        self.assertEqual(self.queries[0][1]["agency"], "%FURG' OR TRUE --%")


if __name__ == "__main__":
    unittest.main()
