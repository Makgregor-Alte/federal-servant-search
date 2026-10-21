"""Teste opcional do filtro de UF em PostgreSQL real."""
import os
import unittest

from app.search import build_search_queries, parse_filters


@unittest.skipUnless(os.environ.get("RUN_DB_INTEGRATION_TESTS") == "1", "requires PostgreSQL test environment")
class UFDatabaseTests(unittest.TestCase):
    def test_filtro_exato_uf_e_registros_sem_estado(self):
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
                        (1, "Ana", "Analista", "FURG", "RS", "carreira"),
                        (2, "Bruna", "Analista", "USP", "SP", "carreira"),
                        (3, "Carlos", "Professor", "FURG", "RS", "carreira"),
                        (4, "Dora", "", "", None, "aposentados"),
                    ],
                )

                def search(args):
                    count_sql, data_sql, params, data_params = build_search_queries(parse_filters(args))
                    cursor.execute(count_sql, params)
                    total = cursor.fetchone()["count"]
                    cursor.execute(data_sql, data_params)
                    return total, [row["id"] for row in cursor.fetchall()]

                self.assertEqual(search({"uf": "rs"}), (2, [1, 3]))
                self.assertEqual(search({"uf": "SP"}), (1, [2]))
                self.assertEqual(search({"uf": "AC"}), (0, []))
                self.assertEqual(search({"uf": "RS", "cargo": "Analista"}), (1, [1]))
                self.assertEqual(search({}), (4, [1, 2, 3, 4]))


if __name__ == "__main__":
    unittest.main()
