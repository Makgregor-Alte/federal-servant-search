"""Index definitions, migration compatibility and PostgreSQL search plans."""
import importlib.util
import os
import re
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "db" / "01_schema.sql"
MIGRATION = ROOT / "db" / "04_indexes.sql"
COMPOSE = ROOT / "docker-compose.yml"
PROFILE = ROOT / "db" / "profile_indexes.py"


def index_names_in_plan(plan):
    """Find index access paths below Limit, Sort and other plan nodes."""
    names = set()
    pending = [plan]
    while pending:
        node = pending.pop()
        if node.get("Index Name"):
            names.add(node["Index Name"])
        pending.extend(node.get("Plans", []))
    return names


class IndexContractTests(unittest.TestCase):
    def test_limit_plan_contains_nested_index_name(self):
        plan = {"Node Type": "Limit", "Plans": [
            {"Node Type": "Index Scan", "Index Name": "idx_servidores_uf_nome"}
        ]}
        self.assertEqual(index_names_in_plan(plan), {"idx_servidores_uf_nome"})

    def test_indexes_match_search_predicates_and_order(self):
        text = SCHEMA.read_text("utf-8")
        self.assertRegex(text, r"idx_servidores_nome_ordenacao\s+ON servidores\s*\(LOWER\(nome\), id\)")
        self.assertRegex(text, r"idx_servidores_uf_nome\s+ON servidores\s*\(uf, LOWER\(nome\), id\)")
        self.assertIn("LOWER(nome) gin_trgm_ops", text)
        self.assertIn("cargo gin_trgm_ops", text)
        self.assertIn("orgao gin_trgm_ops", text)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS pg_trgm", text)

    def test_migration_preserves_data_and_replaces_redundant_indexes(self):
        text = MIGRATION.read_text("utf-8")
        self.assertIn("CREATE INDEX IF NOT EXISTS idx_servidores_nome_ordenacao", text)
        self.assertIn("CREATE INDEX IF NOT EXISTS idx_servidores_uf_nome", text)
        self.assertIn("DROP INDEX IF EXISTS idx_servidores_nome_exato", text)
        self.assertIn("DROP INDEX IF EXISTS idx_servidores_uf;", text)
        self.assertNotRegex(text, r"(?i)\b(?:DROP|TRUNCATE)\s+TABLE\b")
        self.assertNotRegex(text, r"(?i)\bDELETE\s+FROM\b")

    def test_compose_mounts_migration_after_previous_scripts(self):
        text = COMPOSE.read_text("utf-8")
        self.assertIn("./db/04_indexes.sql:/docker-entrypoint-initdb.d/04_indexes.sql:ro", text)
        self.assertLess(text.index("/03_integrity.sql:ro"), text.index("/04_indexes.sql:ro"))

    def test_profile_tool_handles_nested_index_nodes(self):
        spec = importlib.util.spec_from_file_location("profile_indexes", PROFILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        summary = module.plan_summary({
            "Planning Time": 0.75,
            "Execution Time": 1.255,
            "Plan": {
                "Actual Rows": 3,
                "Plans": [{"Index Name": "idx_servidores_nome_similar"},
                          {"Plans": [{"Index Name": "idx_servidores_uf_nome"}]}],
            },
        })
        self.assertEqual(summary["indexes"], ["idx_servidores_nome_similar", "idx_servidores_uf_nome"])
        self.assertEqual(summary["execution_ms"], 1.255)
        self.assertEqual(summary["returned_rows"], 3)


@unittest.skipUnless(os.environ.get("RUN_DB_INTEGRATION_TESTS") == "1", "requires PostgreSQL")
class RealPostgresIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql

        cls.psycopg = psycopg
        cls.sql = sql
        cls.conn = psycopg.connect(os.environ.get("DATABASE_URL") or "", autocommit=True,
                                   connect_timeout=5)
        cls.schema = "test_indexes_" + uuid.uuid4().hex[:12]
        try:
            with cls.conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
                if cur.fetchone() is None:
                    raise AssertionError("A extensão pg_trgm não foi instalada")
                cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
                cur.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(cls.schema)))
                schema_sql = re.sub(r"CREATE EXTENSION IF NOT EXISTS pg_trgm;\s*", "",
                                    SCHEMA.read_text("utf-8"), count=1)
                cur.execute(schema_sql)
                cur.execute((ROOT / "db" / "02_model.sql").read_text("utf-8"))
                cur.execute((ROOT / "db" / "03_integrity.sql").read_text("utf-8"))
                # Reproduce an existing database that still uses the old indexes.
                cur.execute("DROP INDEX idx_servidores_nome_ordenacao")
                cur.execute("DROP INDEX idx_servidores_uf_nome")
                cur.execute("CREATE INDEX idx_servidores_nome_exato ON servidores (LOWER(nome))")
                cur.execute("CREATE INDEX idx_servidores_uf ON servidores (uf)")
                cur.execute(MIGRATION.read_text("utf-8"))
                cur.execute(MIGRATION.read_text("utf-8"))
                cur.execute("""
                    INSERT INTO servidores (nome, cargo, orgao, uf, fonte, id_origem)
                    SELECT CASE WHEN g % 10 = 0 THEN 'Ana Souza' ELSE 'Pessoa ' || g END,
                           CASE WHEN g % 3 = 0 THEN 'Analista' ELSE 'Docente' END,
                           'Universidade Federal',
                           CASE WHEN g % 2 = 0 THEN 'RS' ELSE 'SC' END,
                           'teste', 'idx-' || g
                    FROM generate_series(1, 600) g
                """)
                cur.execute("ANALYZE servidores")
        except BaseException:
            cls._cleanup()
            raise

    @classmethod
    def _cleanup(cls):
        try:
            with cls.conn.cursor() as cur:
                cur.execute(cls.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    cls.sql.Identifier(cls.schema)))
        finally:
            cls.conn.close()

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    def test_legacy_indexes_replaced_without_data_loss(self):
        with self.conn.cursor() as cur:
            cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = %s", (self.schema,))
            names = {row[0] for row in cur.fetchall()}
            self.assertTrue({"idx_servidores_nome_ordenacao", "idx_servidores_uf_nome",
                             "idx_servidores_nome_similar", "idx_servidores_cargo",
                             "idx_servidores_orgao"}.issubset(names))
            self.assertFalse({"idx_servidores_nome_exato", "idx_servidores_uf"} & names)
            cur.execute("SELECT COUNT(*) FROM servidores")
            self.assertEqual(cur.fetchone()[0], 600)

    def test_btree_supports_uf_filter_and_stable_order(self):
        with self.conn.cursor() as cur:
            cur.execute("SET enable_seqscan = off")
            try:
                cur.execute("""
                    EXPLAIN (FORMAT JSON)
                    SELECT id, nome FROM servidores
                    WHERE uf = 'RS' ORDER BY LOWER(nome), id LIMIT 20
                """)
                plan = cur.fetchone()[0][0]["Plan"]
                self.assertTrue(
                    index_names_in_plan(plan) & {
                        "idx_servidores_uf_nome", "idx_servidores_nome_ordenacao"
                    },
                    f"Nenhum indice compativel no plano: {plan.get('Node Type')}",
                )
            finally:
                cur.execute("RESET enable_seqscan")

            cur.execute("""
                SELECT uf, nome, id FROM servidores
                WHERE uf = 'RS' ORDER BY LOWER(nome), id LIMIT 20
            """)
            rows = cur.fetchall()
            self.assertEqual(len(rows), 20)
            self.assertTrue(all(uf == "RS" for uf, _, _ in rows))
            ordering = [(nome.lower(), row_id) for _, nome, row_id in rows]
            self.assertEqual(ordering, sorted(ordering))

    def test_name_similarity_and_textual_filters_keep_results(self):
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM servidores WHERE LOWER(nome) LIKE %s", ("%ana%",))
            self.assertEqual(cur.fetchone()[0], 60)
            cur.execute("SELECT COUNT(*) FROM servidores WHERE cargo ILIKE %s", ("%analista%",))
            self.assertEqual(cur.fetchone()[0], 200)
            cur.execute("SELECT COUNT(*) FROM servidores WHERE orgao ILIKE %s", ("%federal%",))
            self.assertEqual(cur.fetchone()[0], 600)
            cur.execute("SELECT COUNT(*) FROM servidores WHERE LOWER(nome) %% LOWER(%s)", ("Ana Souza",))
            self.assertGreaterEqual(cur.fetchone()[0], 60)


if __name__ == "__main__":
    unittest.main()
