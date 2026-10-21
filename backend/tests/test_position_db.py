"""Optional PostgreSQL acceptance test for cargo/profissão searches."""
import os
import unittest

from app.search import build_search_queries, parse_filters


@unittest.skipUnless(os.environ.get("RUN_DB_INTEGRATION_TESTS") == "1", "requires PostgreSQL test environment")
class PositionDatabaseTests(unittest.TestCase):
    def test_cargo_case_partial_literal_wildcards_and_no_matches(self):
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
                        (1, "Ana", "Analista de Sistemas", "FURG", "RS", "carreira"),
                        (2, "Bruna", "ANALISTA DE SISTEMAS", "FURG", "RS", "carreira"),
                        (3, "Carlos", "Técnico em Informática", "UFPEL", "RS", "carreira"),
                        (4, "Dora", "Engenheiro 100%_Teste", "IFRS", "RS", "carreira"),
                        (5, "Eva", "Pesquisadora", "IFRS", "RS", "carreira"),
                    ],
                )

                def search(value):
                    count_sql, data_sql, params, paging = build_search_queries(parse_filters({"cargo": value}))
                    cursor.execute(count_sql, params)
                    total = cursor.fetchone()["count"]
                    cursor.execute(data_sql, paging)
                    return total, [row["id"] for row in cursor.fetchall()]

                self.assertEqual(search("analista"), (2, [1, 2]))
                self.assertEqual(search("  Técnico   em   Informática "), (1, [3]))
                self.assertEqual(search("100%_Teste"), (1, [4]))
                self.assertEqual(search("100%Teste"), (0, []))
                self.assertEqual(search("Cargo Inexistente"), (0, []))
                self.assertEqual(search("' OR TRUE --"), (0, []))


if __name__ == "__main__":
    unittest.main()
