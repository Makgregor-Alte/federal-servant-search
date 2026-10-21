"""PostgreSQL integration checks for searches by institution or agency."""
import os
import unittest

from app.search import build_search_queries, parse_filters


@unittest.skipUnless(os.environ.get("RUN_DB_INTEGRATION_TESTS") == "1", "requires PostgreSQL test environment")
class AgencyDatabaseTests(unittest.TestCase):
    def test_case_partial_combination_and_literal_wildcards(self):
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
                        (1, "Ana", "Analista", "Universidade Federal do Rio Grande", "RS", "carreira"),
                        (2, "Bruna", "Professora", "UNIVERSIDADE FEDERAL DO RIO GRANDE", "RS", "carreira"),
                        (3, "Carlos", "Analista", "Instituto Federal Sul-rio-grandense", "RS", "carreira"),
                        (4, "Dora", "Analista", "Órgão 100%_Teste", "SP", "carreira"),
                        (5, "Eva", "", "", None, "aposentados"),
                    ],
                )

                def search(args):
                    count_sql, data_sql, params, data_params = build_search_queries(parse_filters(args))
                    cursor.execute(count_sql, params)
                    total = cursor.fetchone()["count"]
                    cursor.execute(data_sql, data_params)
                    return total, [row["id"] for row in cursor.fetchall()]

                self.assertEqual(search({"orgao": "universidade federal"}), (2, [1, 2]))
                self.assertEqual(search({"agency": "universidade", "cargo": "analista", "uf": "RS"}), (1, [1]))
                self.assertEqual(search({"orgao": "100%_Teste"}), (1, [4]))
                self.assertEqual(search({"orgao": "100%Teste"}), (0, []))
                self.assertEqual(search({"orgao": "Órgão Inexistente"}), (0, []))
                self.assertEqual(search({"orgao": "' OR TRUE --"}), (0, []))
                self.assertEqual(search({}), (5, [1, 2, 3, 4, 5]))


if __name__ == "__main__":
    unittest.main()
