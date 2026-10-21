"""HTTP-level tests for intersections of search filters."""
import unittest
from unittest.mock import patch

from app import create_app


class RecordingCursor:
    def __init__(self, statements, results):
        self.statements = statements
        self.results = results

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchone(self):
        return {"count": len(self.results)}

    def fetchall(self):
        return self.results


class RecordingConnection:
    def __init__(self, statements, results):
        self.cursor_obj = RecordingCursor(statements, results)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self.cursor_obj


class CombinedHttpTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.testing = True
        self.client = app.test_client()
        self.statements = []

    def test_combined_filters_forwarded_to_count_and_data_queries(self):
        row = {"id": 21, "nome": "Maria Silva", "cargo": "Analista",
               "orgao": "Universidade Federal", "uf": "RS", "fonte": "carreiras"}
        with patch("app.routes.connect_db", return_value=RecordingConnection(self.statements, [row])):
            response = self.client.get("/api/servidores", query_string={
                "similar": "MAR%SILVA%", "cargo": "Analista", "orgao": "Universidade",
                "uf": "rs", "pagina": "1", "limit": "5"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["items"], [row])
        self.assertEqual(response.json["pagination"], {
            "page": 1, "page_size": 5, "total": 1, "pages": 1})
        self.assertEqual(len(self.statements), 2)
        self.assertEqual(self.statements[0][1], {
            "name": "MAR%SILVA%", "name_pattern": "MAR%SILVA%",
            "position": "%Analista%", "agency": "%Universidade%", "uf": "RS"})
        self.assertEqual(self.statements[1][1]["offset"], 0)

    def test_invalid_combination_rejected_without_database_call(self):
        cases = (
            {"nome": "Ana", "similar": "%Ana%", "uf": "RS"},
            {"nome": "Ana", "cargo": "Analista", "position": "Analista"},
            {"cargo": "Analista", "orgao": "FURG", "agency": "FURG"},
            {"nome": "Ana", "uf": "XX"},
        )
        with patch("app.routes.connect_db") as connect:
            for params in cases:
                with self.subTest(params=params):
                    resp = self.client.get("/api/servidores", query_string=params)
                    self.assertEqual(resp.status_code, 400)
                    self.assertEqual(resp.json["error"], "invalid_parameters")
        connect.assert_not_called()

    def test_combined_zero_results_return_valid_empty_json(self):
        with patch("app.routes.connect_db", return_value=RecordingConnection(self.statements, [])):
            response = self.client.get("/api/servidores?nome=Ana&cargo=Inexistente&uf=RS")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["items"], [])
        self.assertEqual(response.json["pagination"]["pages"], 0)


if __name__ == "__main__":
    unittest.main()
