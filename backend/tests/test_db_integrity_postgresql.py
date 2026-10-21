"""Testes opcionais de integridade com PostgreSQL isolado."""

import os
import re
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "db"))


@unittest.skipUnless(os.getenv("RUN_DB_INTEGRATION_TESTS") == "1", "requires PostgreSQL")
class RealIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        from import_bulk import run_bulk
        from import_sample import make_sample, import_sample
        from integrity import audit_connection

        cls.psycopg = psycopg
        cls.sql = sql
        cls.run_bulk = staticmethod(run_bulk)
        cls.make_sample = staticmethod(make_sample)
        cls.import_sample = staticmethod(import_sample)
        cls.audit_connection = staticmethod(audit_connection)
        cls.conn = psycopg.connect(os.getenv("DATABASE_URL") or "",
                                   autocommit=True, connect_timeout=5)
        cls.schema = "test_integrity_" + uuid.uuid4().hex[:14]
        cls.tmp = tempfile.TemporaryDirectory()
        cls.file = Path(cls.tmp.name) / "aposentados.csv"
        try:
            with cls.conn.cursor() as cur:
                cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
                cur.execute(sql.SQL("SET search_path TO {}, public").format(
                    sql.Identifier(cls.schema)))
                bootstrap = (ROOT / "db" / "01_schema.sql").read_text("utf-8")
                bootstrap = re.sub(r"CREATE EXTENSION IF NOT EXISTS pg_trgm;\s*", "",
                                   bootstrap, count=1)
                cur.execute(bootstrap)
                cur.execute((ROOT / "db" / "02_model.sql").read_text("utf-8"))
                migration = (ROOT / "db" / "03_integrity.sql").read_text("utf-8")
                cur.execute(migration)
                cur.execute(migration)
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
            cls.tmp.cleanup()

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    def setUp(self):
        with self.conn.cursor() as cur:
            cur.execute("TRUNCATE servidores, lotes_importacao RESTART IDENTITY")

    def write(self, *lines):
        self.file.write_text("Nome;Cargo;Nome do órgão\n" +
                             "\n".join(lines) + "\n", encoding="utf-8")

    def test_same_identity_new_competence_rejected_with_existing_rows_unchanged(self):
        self.write("Ana;Docente;Universidade", "Ana;Docente;Universidade")
        original = self.run_bulk(self.file, "aposentados", competence="2026-05",
                                 batch_size=1, connection=self.conn)
        with self.assertRaisesRegex(ValueError, "Identificador"):
            self.run_bulk(self.file, "aposentados", competence="2026-06",
                          batch_size=1, connection=self.conn)
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), MIN(competencia), MAX(competencia) FROM servidores")
            total, start, end = cur.fetchone()
            self.assertEqual(total, 2)
            self.assertEqual(start.isoformat(), "2026-05-01")
            self.assertEqual(start, end)
            cur.execute("SELECT estado FROM lotes_importacao ORDER BY id")
            self.assertEqual([v[0] for v in cur.fetchall()], ["concluido", "falhou"])
        self.assertEqual(original["importadas"], 2)

    def test_sample_then_bulk_same_month_uses_same_identity(self):
        self.write(*[f"Servidor {n:03d};Analista;Instituto" for n in range(100)])
        sample = self.make_sample(self.file, "aposentados", competence="2026-05")
        first = self.import_sample(self.conn, sample)
        second = self.run_bulk(self.file, "aposentados", competence="2026-05",
                               connection=self.conn)
        self.assertEqual(first["importadas"], 100)
        self.assertEqual((second["importadas"], second["ja_existentes"]), (0, 100))
        audit = self.audit_connection(self.conn)
        self.assertEqual(audit["registros_divergentes_do_lote"], 0)
        self.assertEqual(audit["fontes"][0]["sem_uf"], 100)

    def test_integrity_constraints_reject_invalid_uf_and_blank_id(self):
        with self.conn.cursor() as cur:
            with self.assertRaises(self.psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO servidores (nome, uf, fonte, id_origem)
                    VALUES ('Nome', 'ZZ', 'carreiras', 'chave-1')
                """)
            with self.assertRaises(self.psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO servidores (nome, fonte, id_origem)
                    VALUES ('Nome', 'aposentados', '  ')
                """)

    def test_sample_detects_conflicting_identity(self):
        self.write(*[f"Servidor {n:03d};Analista;Instituto" for n in range(100)])
        original = self.make_sample(self.file, "aposentados", competence="2026-05")
        self.import_sample(self.conn, original)
        changed = self.make_sample(self.file, "aposentados", competence="2026-06")
        with self.assertRaisesRegex(ValueError, "Identificador"):
            self.import_sample(self.conn, changed)
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM lotes_importacao")
            self.assertEqual(cur.fetchone()[0], 1)  # Transação da amostra revertida.


if __name__ == "__main__":
    unittest.main()
