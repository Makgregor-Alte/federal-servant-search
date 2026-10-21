"""Real PostgreSQL checks for multi-field search intersections."""
import os
import unittest

from app.search import build_search_queries, parse_filters


@unittest.skipUnless(os.environ.get("RUN_DB_INTEGRATION_TESTS") == "1", "requires PostgreSQL test environment")
class CombinedDatabaseTests(unittest.TestCase):
    def test_exact_similar_pattern_and_pagination_with_cross_matches(self):
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(os.environ.get("DATABASE_URL", ""), row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                cursor.execute("""CREATE TEMP TABLE servidores (
                    id BIGINT PRIMARY KEY, nome TEXT NOT NULL, cargo TEXT,
                    orgao TEXT, uf CHAR(2), fonte TEXT
                ) ON COMMIT DROP""")
                rows = [
                    (1, "Maria Silva", "Analista de Sistemas", "Universidade Federal", "RS", "carreira"),
                    (2, "Maria Silva", "Professora", "Universidade Federal", "RS", "carreira"),
                    (3, "Maria Silva", "Analista de Sistemas", "Universidade Federal", "SP", "carreira"),
                    (4, "Marina Silva", "Analista de Sistemas", "Universidade Federal", "RS", "carreira"),
                    (5, "João Silva", "Analista de Sistemas", "Universidade Federal", "RS", "carreira"),
                    (6, "Maria Silva", "Analista de Sistemas", "Universidade Federal", None, "aposentados"),
                    (7, "Ana Maria Silva", "Analista de Sistemas", "Universidade Federal", "RS", "carreira"),
                    (8, "Maria Silva", "Analista de Sistemas", "Instituto Federal", "RS", "carreira"),
                    (9, "Maria Silva", "Analista de Sistemas", "Universidade Federal", "SC", "carreira"),
                    (10, "MARIA SILVA", "ANALISTA DE SISTEMAS", "Universidade Federal", "RS", "carreira"),
                ]
                cursor.executemany(
                    "INSERT INTO servidores (id, nome, cargo, orgao, uf, fonte) VALUES (%s, %s, %s, %s, %s, %s)",
                    rows,
                )

                def query(args):
                    count, select, params, page_params = build_search_queries(parse_filters(args))
                    cursor.execute(count, params)
                    total = cursor.fetchone()["count"]
                    cursor.execute(select, page_params)
                    return total, [row["id"] for row in cursor.fetchall()]

                exact = {"nome": "Maria Silva", "cargo": "Analista", "orgao": "Universidade", "uf": "RS"}
                total, ids = query(exact)
                self.assertEqual(total, 2)
                self.assertEqual(set(ids), {1, 10})
                self.assertEqual(query({"nome": "Maria Silva", "cargo": "Professora", "uf": "RS"}), (1, [2]))
                self.assertEqual(query({"nome": "Maria Silva", "cargo": "Analista", "uf": "TO"}), (0, []))
                self.assertEqual(query({"similar": "MAR%SILVA%", "cargo": "Analista",
                                        "orgao": "Universidade", "uf": "RS"})[0], 3)
                fuzzy_total, fuzzy_ids = query({"similar": "Marina Silva", "cargo": "Analista",
                                                "orgao": "Universidade", "uf": "RS"})
                self.assertGreaterEqual(fuzzy_total, 1)
                self.assertIn(4, fuzzy_ids)
                total1, ids1 = query(dict(exact, limit="1", page="1"))
                total2, ids2 = query(dict(exact, limit="1", page="2"))
                self.assertEqual((total1, total2), (2, 2))
                self.assertEqual(set(ids1 + ids2), {1, 10})
                self.assertEqual(query({"cargo": "Analista", "orgao": "Universidade", "uf": "TO"}), (0, []))


if __name__ == "__main__":
    unittest.main()
