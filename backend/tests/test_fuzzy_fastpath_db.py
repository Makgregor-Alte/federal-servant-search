"""Optional real PostgreSQL verification, using a temporary table only."""
import os
import unittest

from app.search import build_fuzzy_prefix_page, build_search_queries, parse_filters


@unittest.skipUnless(os.getenv("RUN_DB_INTEGRATION_TESTS") == "1", "requires isolated PostgreSQL tests")
class FuzzyFastPathDatabaseTests(unittest.TestCase):
    def test_count_and_complete_prefix_pages_are_identical(self):
        import psycopg
        from psycopg.rows import dict_row

        names = (
            "Mariana", "Mariana Silva", "Mariana Rosa", "Mariana Oliveira",
            "Ana Mariana", "Maria", "Mario", "Joao", "Joao Mariana",
        )
        with psycopg.connect(os.environ.get("DATABASE_URL", ""), row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                cursor.execute("""CREATE TEMP TABLE servidores (
                    id BIGINT PRIMARY KEY, nome TEXT NOT NULL, cargo TEXT,
                    orgao TEXT, uf CHAR(2), fonte TEXT
                ) ON COMMIT DROP""")
                cursor.executemany(
                    "INSERT INTO servidores (id, nome, cargo, orgao, uf, fonte) "
                    "VALUES (%s, %s, 'cargo', 'orgao', 'RS', 'test')",
                    [(index, name) for index, name in enumerate(names, start=1)],
                )
                for number in (1, 2, 3, 4):
                    with self.subTest(page=number):
                        filt = parse_filters({"similar": "Mariana", "page": str(number), "limit": "2"})
                        count_sql, data_sql, params, data_params = build_search_queries(filt)
                        cursor.execute(count_sql, params)
                        proposed_total = cursor.fetchone()["count"]
                        old_sql = (
                            "SELECT COUNT(*) FROM servidores WHERE "
                            "(LOWER(nome) %% LOWER(%(name)s) OR "
                            "LOWER(nome) LIKE LOWER(%(name_pattern)s) ESCAPE '\\')"
                        )
                        cursor.execute(old_sql, params)
                        self.assertEqual(proposed_total, cursor.fetchone()["count"])
                        cursor.execute(data_sql, data_params)
                        standard_page = [r["id"] for r in cursor.fetchall()]
                        candidate = build_fuzzy_prefix_page(filt)
                        self.assertIsNotNone(candidate)
                        prefix_sql, prefix_params = candidate
                        cursor.execute(prefix_sql, prefix_params)
                        prefix_page = [r["id"] for r in cursor.fetchall()]
                        if len(prefix_page) == filt.page_size:
                            self.assertEqual(prefix_page, standard_page)
                        else:
                            self.assertLess(len(prefix_page), filt.page_size)


if __name__ == "__main__":
    unittest.main()
