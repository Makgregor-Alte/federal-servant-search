"""Route-level regression tests, using a deterministic fake database cursor."""
import unittest
from unittest.mock import patch

from app import create_app


class FakeCursor:
    def __init__(self, count, prefix_rows, full_rows):
        self.count, self.prefix_rows, self.full_rows = count, prefix_rows, full_rows
        self.sql = None
        self.log = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.sql = sql
        self.log.append((sql, params))

    def fetchone(self):
        return {"count": self.count}

    def fetchall(self):
        if "WHERE LOWER(nome) LIKE LOWER(%(name_prefix)s)" in self.sql.split("ORDER BY")[0]:
            return self.prefix_rows
        return self.full_rows


class FakeConnection:
    def __init__(self, cursor):
        self.value = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self.value


class FuzzyFastPathHttpTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def query(self, cursor, params):
        with patch("app.routes.connect_db", return_value=FakeConnection(cursor)) as connect:
            response = self.client.get("/api/servidores?" + params)
        self.assertEqual(connect.call_args.kwargs["fuzzy"], True)
        return response

    def test_filled_prefix_page_skips_full_fuzzy_select(self):
        rows = [{"id": n} for n in range(1, 21)]
        cursor = FakeCursor(6377, rows, [{"id": 999}])
        response = self.query(cursor, "similar=Mariana&page=1&page_size=20")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["pagination"]["total"], 6377)
        self.assertEqual(response.json["items"], rows)
        self.assertEqual(len(cursor.log), 2)
        self.assertIn(" UNION ", cursor.log[0][0])

    def test_short_prefix_page_falls_back_to_full_fuzzy_select(self):
        rows = [{"id": n} for n in range(1, 21)]
        cursor = FakeCursor(6377, rows[:4], rows)
        response = self.query(cursor, "similar=Mariana&page=2&page_size=20")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["items"], rows)
        self.assertEqual(len(cursor.log), 3)
        self.assertIn("OR LOWER(nome) LIKE", cursor.log[2][0].split("ORDER BY")[0])

    def test_combined_fuzzy_keeps_two_statements(self):
        cursor = FakeCursor(1, [], [{"id": 10}])
        response = self.query(cursor, "similar=Mariana&uf=RS&page=1&page_size=20")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["items"], [{"id": 10}])
        self.assertEqual(len(cursor.log), 2)
        self.assertNotIn(" UNION ", cursor.log[0][0])

    def test_out_of_range_does_not_run_page_queries(self):
        cursor = FakeCursor(2, [], [{"id": 10}])
        response = self.query(cursor, "similar=Mariana&page=10&page_size=20")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(cursor.log), 1)


if __name__ == "__main__":
    unittest.main()
