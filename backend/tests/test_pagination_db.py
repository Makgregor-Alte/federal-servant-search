"""Optional pagination integration checks using a real PostgreSQL transaction."""
import os
import unittest

from app.search import build_search_queries, pagination, parse_filters


@unittest.skipUnless(os.environ.get("RUN_DB_INTEGRATION_TESTS") == "1", "requires PostgreSQL test environment")
class PaginationDatabaseTests(unittest.TestCase):
    def test_stable_pages_and_count(self):
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(os.environ.get("DATABASE_URL", ""), row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                cursor.execute("""CREATE TEMP TABLE servidores (
                    id BIGINT PRIMARY KEY, nome TEXT NOT NULL, cargo TEXT,
                    orgao TEXT, uf CHAR(2), fonte TEXT
                ) ON COMMIT DROP""")
                cursor.executemany(
                    "INSERT INTO servidores (id, nome, cargo, orgao, uf, fonte) VALUES (%s, %s, %s, %s, %s, %s)",
                    [
                        (3, "Ana", "Analista", "FURG", "RS", "carreira"),
                        (2, "ANA", "Analista", "FURG", "RS", "carreira"),
                        (1, "Beatriz", "Analista", "FURG", "RS", "carreira"),
                        (5, "Carlos", "Analista", "FURG", "RS", "carreira"),
                        (4, "Daniela", "Analista", "FURG", "RS", "carreira"),
                    ],
                )
                combined_ids = []
                for page, expected_ids in ((1, [2, 3]), (2, [1, 5]), (3, [4])):
                    filters = parse_filters({"cargo": "Analista", "uf": "RS", "pagina": str(page), "limit": "2"})
                    count, select, count_params, select_params = build_search_queries(filters)
                    cursor.execute(count, count_params)
                    total = cursor.fetchone()["count"]
                    cursor.execute(select, select_params)
                    ids = [row["id"] for row in cursor.fetchall()]
                    self.assertEqual(pagination(total, filters)["pages"], 3)
                    self.assertEqual(total, 5)
                    self.assertEqual(ids, expected_ids)
                    combined_ids.extend(ids)
                self.assertEqual(len(set(combined_ids)), 5)


if __name__ == "__main__":
    unittest.main()
