"""Optional exact-name SQL acceptance test against PostgreSQL.

Set RUN_DB_INTEGRATION_TESTS=1 and provide PostgreSQL connection variables.
"""
import os
import unittest

from app.search import build_search_queries, parse_filters


@unittest.skipUnless(os.environ.get("RUN_DB_INTEGRATION_TESTS") == "1", "requires PostgreSQL test environment")
class ExactDatabaseTests(unittest.TestCase):
    def test_matching_names_and_literal_wildcards(self):
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(os.environ.get("DATABASE_URL", ""), row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                cursor.execute("""CREATE TEMP TABLE servidores (
                    id BIGINT PRIMARY KEY,
                    nome TEXT NOT NULL,
                    cargo TEXT,
                    orgao TEXT,
                    uf CHAR(2),
                    fonte TEXT
                ) ON COMMIT DROP""")
                cursor.executemany(
                    "INSERT INTO servidores (id, nome, cargo, orgao, uf, fonte) VALUES (%s, %s, %s, %s, %s, %s)",
                    [
                        (1, "Maria da Silva", "Analista", "FURG", "RS", "carreira"),
                        (2, "MARIA DA SILVA", "Tecnica", "FURG", "RS", "carreira"),
                        (3, "Mariana da Silva", "Analista", "FURG", "RS", "carreira"),
                        (4, "Ana_% Silva", "Analista", "FURG", "RS", "carreira"),
                        (5, "José da Silva", "Analista", "FURG", "RS", "carreira"),
                    ],
                )
                samples = [
                    ("  maria  da   silva ", [1, 2]),
                    ("Ana_% Silva", [4]),
                    ("Jose\u0301 da Silva", [5]),
                    ("inexistente", []),
                ]
                for text, expected in samples:
                    with self.subTest(text=text):
                        count_sql, data_sql, params, paging = build_search_queries(parse_filters({"nome": text}))
                        cursor.execute(count_sql, params)
                        count = cursor.fetchone()["count"]
                        cursor.execute(data_sql, paging)
                        rows = cursor.fetchall()
                        self.assertEqual(count, len(expected))
                        self.assertEqual(sorted(row["id"] for row in rows), expected)


if __name__ == "__main__":
    unittest.main()
