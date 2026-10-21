"""Verificações do esquema relacional e de migração PostgreSQL."""
import os
import re
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "db" / "01_schema.sql"
MIGRATION = ROOT / "db" / "02_model.sql"
COMPOSE = ROOT / "docker-compose.yml"


class ModelContractTests(unittest.TestCase):
    def test_legacy_api_columns_are_preserved(self):
        text = SCHEMA.read_text(encoding="utf-8")
        for column in ("id", "nome", "cargo", "orgao", "uf", "fonte", "id_origem"):
            with self.subTest(column=column):
                self.assertRegex(text, rf"(?m)^\s*{column}\s+(?:BIGINT|TEXT|CHAR\(2\))(?=\s|,)")
        self.assertIn("UNIQUE (fonte, id_origem)", text)

    def test_migration_does_not_redefine_or_drop_legacy_tables(self):
        text = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS lotes_importacao", text)
        self.assertIn("ADD COLUMN IF NOT EXISTS competencia DATE", text)
        self.assertIn("ADD COLUMN IF NOT EXISTS lote_importacao_id BIGINT", text)
        self.assertIn("REFERENCES lotes_importacao (id) ON DELETE RESTRICT", text)
        self.assertNotRegex(text, r"(?i)\b(?:DROP|TRUNCATE)\s+TABLE\b")
        self.assertNotRegex(text, r"(?i)\bDELETE\s+FROM\s+servidores\b")

    def test_compose_runs_both_scripts_for_new_volumes(self):
        text = COMPOSE.read_text(encoding="utf-8")
        self.assertIn("./db/01_schema.sql:/docker-entrypoint-initdb.d/01_schema.sql:ro", text)
        self.assertIn("./db/02_model.sql:/docker-entrypoint-initdb.d/02_model.sql:ro", text)
        self.assertLess(text.index("/01_schema.sql:ro"), text.index("/02_model.sql:ro"))


@unittest.skipUnless(os.environ.get("RUN_DB_INTEGRATION_TESTS") == "1", "requires PostgreSQL")
class RealPostgresModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql

        cls.psycopg = psycopg
        cls.sql = sql
        cls.conn = psycopg.connect(os.environ.get("DATABASE_URL") or "", autocommit=True)
        cls.schema = "test_model_" + uuid.uuid4().hex[:16]
        try:
            with cls.conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
                if cur.fetchone() is None:
                    raise AssertionError("pg_trgm ausente; inicialize db/01_schema.sql")
                cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
                cur.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(cls.schema)))
                bootstrap = SCHEMA.read_text(encoding="utf-8")
                bootstrap = re.sub(r"CREATE EXTENSION IF NOT EXISTS pg_trgm;\s*", "", bootstrap, count=1)
                cur.execute(bootstrap)
                cur.execute(MIGRATION.read_text(encoding="utf-8"))
                cur.execute(MIGRATION.read_text(encoding="utf-8"))
        except BaseException:
            try:
                with cls.conn.cursor() as cur:
                    cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(cls.schema)))
            finally:
                cls.conn.close()
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            with cls.conn.cursor() as cur:
                cur.execute(cls.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(cls.sql.Identifier(cls.schema)))
        finally:
            cls.conn.close()

    def test_migration_idempotent_and_relationship_created(self):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'servidores'::regclass
            """)
            constraints = {r[0] for r in cur.fetchall()}
        self.assertIn("servidores_lote_importacao_fk", constraints)
        self.assertIn("servidores_competencia_primeiro_dia_ck", constraints)
        self.assertIn("servidores_fonte_id_origem_unique", constraints)

    def test_legacy_insert_and_nullable_provenance(self):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO servidores (nome, cargo, orgao, uf, fonte, id_origem)
                VALUES ('Pessoa de Teste', 'Docente', 'Universidade', NULL, 'aposentados', 'legado-01')
                RETURNING competencia, lote_importacao_id
            """)
            self.assertEqual(cur.fetchone(), (None, None))

    def test_valid_batch_and_referenced_record(self):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO lotes_importacao
                    (fonte, nome_arquivo, competencia, sha256)
                VALUES ('carreiras', 'amostra.txt', DATE '2026-05-01', %s)
                RETURNING id
            """, ("a" * 64,))
            batch_id = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO servidores
                    (nome, cargo, orgao, uf, fonte, id_origem, competencia, lote_importacao_id)
                VALUES ('Outra Pessoa', 'Analista', 'Universidade', 'RS',
                        'carreiras', 'id-02', DATE '2026-05-01', %s)
                RETURNING lote_importacao_id
            """, (batch_id,))
            self.assertEqual(cur.fetchone()[0], batch_id)

    def test_rejects_invalid_month_and_nonexistent_batch(self):
        with self.conn.cursor() as cur:
            with self.assertRaises(self.psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO servidores (nome, fonte, id_origem, competencia)
                    VALUES ('Teste', 'carreiras', 'data-invalida', DATE '2026-05-02')
                """)
            with self.assertRaises(self.psycopg.errors.ForeignKeyViolation):
                cur.execute("""
                    INSERT INTO servidores (nome, fonte, id_origem, lote_importacao_id)
                    VALUES ('Teste', 'carreiras', 'lote-invalido', -1)
                """)
            with self.assertRaises(self.psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO lotes_importacao (fonte, nome_arquivo, linhas_lidas)
                    VALUES ('carreiras', 'amostra.txt', -1)
                """)


if __name__ == "__main__":
    unittest.main()
