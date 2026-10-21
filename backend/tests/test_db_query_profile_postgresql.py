"""Optional PostgreSQL execution of query profiling on isolated synthetic records."""
import importlib.util
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("profile_indexes", ROOT / "db" / "profile_indexes.py")
PROFILER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILER)


@unittest.skipUnless(os.environ.get("RUN_DB_INTEGRATION_TESTS") == "1", "requires PostgreSQL")
class PostgresQueryProfileTests(unittest.TestCase):
    def test_real_count_and_combined_queries_can_be_profiled_read_only(self):
        import psycopg
        from app.search import build_search_queries, parse_filters

        with psycopg.connect(os.environ.get("DATABASE_URL") or "", connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("""CREATE TEMP TABLE servidores (
                    id BIGINT PRIMARY KEY, nome TEXT NOT NULL,
                    cargo TEXT NOT NULL, orgao TEXT NOT NULL,
                    uf CHAR(2), fonte TEXT NOT NULL
                ) ON COMMIT PRESERVE ROWS""")
                cur.execute("""INSERT INTO servidores(id, nome, cargo, orgao, uf, fonte)
                    SELECT g, CASE WHEN g % 10 = 0 THEN 'Ana Souza' ELSE 'Pessoa ' || g END,
                           CASE WHEN g % 2 = 0 THEN 'Analista' ELSE 'Docente' END,
                           'Universidade Federal',
                           CASE WHEN g % 2 = 0 THEN 'RS' ELSE 'SC' END,
                           'teste'
                    FROM generate_series(1, 1000) AS g""")
                cur.execute("ANALYZE servidores")
            conn.commit()

            fields = {"nome": "Ana Souza", "cargo": "Analista", "uf": "RS"}
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                    filters = parse_filters(dict(fields, limit="10"))
                    count_sql, data_sql, count_params, data_params = build_search_queries(filters)
                    cur.execute(count_sql, count_params)
                    self.assertEqual(cur.fetchone()[0], 100)
                    cur.execute(data_sql, data_params)
                    self.assertEqual(len(cur.fetchall()), 10)
                    metrics = PROFILER.profile_case(cur, fields, repeats=2, warmups=0, limit=10)
                    self.assertEqual(metrics["count"]["samples"], 2)
                    self.assertEqual(metrics["results"]["returned_rows"], 10)
                    self.assertGreaterEqual(metrics["count"]["median_ms"], 0)


if __name__ == "__main__":
    unittest.main()
