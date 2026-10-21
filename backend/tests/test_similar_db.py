import os
import unittest

from app.search import build_search_queries, parse_filters


@unittest.skipUnless(os.environ.get("RUN_DB_INTEGRATION_TESTS") == "1", "requires PostgreSQL test environment")
class SimilarDatabaseTests(unittest.TestCase):
    def test_real_sql_pattern_fuzzy_and_pagination(self):
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(os.environ.get("DATABASE_URL", ""), row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                cursor.execute("""CREATE TEMP TABLE servidores (
                    id BIGINT PRIMARY KEY, nome TEXT NOT NULL, cargo TEXT,
                    orgao TEXT, uf CHAR(2), fonte TEXT
                ) ON COMMIT DROP""")
                cursor.executemany(
                    "INSERT INTO servidores (id, nome, cargo, orgao, uf, fonte) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    [
                        (1, "MARIA SOUZA", "Analista", "FURG", "RS", "carreira"),
                        (2, "MARIA OLIVEIRA SOUZA", "Analista", "FURG", "RS", "carreira"),
                        (3, "JOSE MARIA SOUZA", "Tecnico", "UFPEL", "RS", "carreira"),
                        (4, "ANA_% SILVA", "Analista", "FURG", "RS", "carreira"),
                        (5, "ANA% SILVA", "Analista", "FURG", "RS", "carreira"),
                    ],
                )

                def search(args):
                    count_sql, data_sql, params, data_params = build_search_queries(parse_filters(args))
                    cursor.execute(count_sql, params)
                    total = cursor.fetchone()["count"]
                    cursor.execute(data_sql, data_params)
                    return total, [row["id"] for row in cursor.fetchall()]

                self.assertEqual(search({"similar": "%MARIA%SOUZA%"}), (3, [3, 2, 1]))
                self.assertEqual(search({"similar": "MARIA SOUZA%"}), (1, [1]))
                self.assertEqual(search({"similar": "MARIA%SOUZA"}), (2, [2, 1]))
                self.assertEqual(search({"similar": r"ANA\%%"}), (1, [5]))
                self.assertEqual(search({"similar": "MARIA%SOUZA", "limit": "1", "page": "2"}), (2, [1]))
                total, names = search({"similar": "MARIA SOUZA"})
                self.assertGreaterEqual(total, 1)
                self.assertEqual(names[0], 1)


if __name__ == "__main__":
    unittest.main()
