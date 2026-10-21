"""HTTP pagination contract with a simulated database connection."""
import unittest
from unittest.mock import patch

from app import create_app


class Cursor:
    def __init__(self, rows, statements):
        self.rows = rows
        self.statements = statements
        self.selected = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        if sql.startswith("SELECT id,"):
            sorted_rows = sorted(self.rows, key=lambda row: (row["nome"].lower(), row["id"]))
            self.selected = sorted_rows[params["offset"]: params["offset"] + params["limit"]]

    def fetchone(self):
        return {"count": len(self.rows)}

    def fetchall(self):
        return self.selected


class Connection:
    def __init__(self, rows, statements):
        self.cursor_value = Cursor(rows, statements)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self.cursor_value


class PaginationHttpTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.testing = True
        self.client = app.test_client()
        self.statements = []
        self.rows = [
            {"id": i, "nome": name, "cargo": "Analista", "orgao": "FURG", "uf": "RS", "fonte": "carreira"}
            for i, name in enumerate(("Beatriz", "ANA", "Ana", "Carlos", "Daniela"), start=1)
        ]

    def fetch(self, url, rows=None):
        with patch("app.routes.connect_db", return_value=Connection(self.rows if rows is None else rows, self.statements)):
            return self.client.get(url)

    def test_first_second_and_last_pages_have_stable_data(self):
        for page, expected in ((1, [2, 3]), (2, [1, 4]), (3, [5])):
            with self.subTest(page=page):
                response = self.fetch(f"/api/servidores?pagina={page}&limit=2")
                self.assertEqual(response.status_code, 200)
                self.assertEqual([r["id"] for r in response.json["items"]], expected)
                self.assertEqual(response.json["pagination"], {
                    "page": page, "page_size": 2, "total": 5, "pages": 3,
                })

    def test_nonexistent_page_is_404_without_select_query(self):
        response = self.fetch("/api/servidores?page=4&page_size=2")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json["error"], "page_not_found")
        self.assertEqual(response.json["items"], [])
        self.assertEqual(response.json["pagination"], {
            "page": 4, "page_size": 2, "total": 5, "pages": 3,
        })
        self.assertEqual(len(self.statements), 1)
        self.assertTrue(self.statements[0][0].startswith("SELECT COUNT(*)"))

    def test_empty_first_page_is_success(self):
        response = self.fetch("/api/servidores?page=1", rows=[])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["items"], [])
        self.assertEqual(response.json["pagination"]["pages"], 0)
        self.assertEqual(len(self.statements), 1)

    def test_empty_database_page_two_is_not_found(self):
        response = self.fetch("/api/servidores?page=2", rows=[])
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json["pagination"]["pages"], 0)
        self.assertEqual(len(self.statements), 1)

    def test_invalid_pagination_does_not_access_database(self):
        with patch("app.routes.connect_db") as connect:
            for query in ("page=", "limit=", "page=2.5", "page=1&page=2", "pagina=0", "limit=101", "page=1_0"):
                with self.subTest(query=query):
                    result = self.client.get("/api/servidores?" + query)
                    self.assertEqual(result.status_code, 400)
                    self.assertEqual(result.json["error"], "invalid_parameters")
        connect.assert_not_called()

    def test_alias_endpoint_and_limit_100(self):
        response = self.fetch("/api/servants?pagina=1&limit=100")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["pagination"]["page_size"], 100)
        self.assertEqual(self.statements[-1][1]["limit"], 100)
        self.assertEqual(self.statements[-1][1]["offset"], 0)


if __name__ == "__main__":
    unittest.main()
