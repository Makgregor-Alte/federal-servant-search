"""Importação experimental e pesquisa Flask em PostgreSQL isolado."""

import os
import re
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "db"))


@unittest.skipUnless(os.environ.get("RUN_DB_INTEGRATION_TESTS") == "1", "requires PostgreSQL")
class RealSampleImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        from app import create_app
        from import_sample import import_sample, make_sample

        cls.psycopg = psycopg
        cls.sql = sql
        cls.make_sample = staticmethod(make_sample)
        cls.import_sample = staticmethod(import_sample)
        cls.schema = "test_sample_" + uuid.uuid4().hex[:16]
        cls.connection = psycopg.connect(os.getenv("DATABASE_URL") or "", autocommit=True)
        cls.app = create_app()
        cls.app.testing = True
        cls.client = cls.app.test_client()
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.file = Path(cls.temp_dir.name) / "aposentados.csv"
        lines = ["Nome;Cargo;Nome do órgão"]
        lines.extend(f"Pessoa {i:04d};Docente;Universidade" for i in range(1100))
        cls.file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            with cls.connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
                if not cursor.fetchone():
                    raise AssertionError("pg_trgm não habilitada")
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
                cursor.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(cls.schema)))
                base = re.sub(r"CREATE EXTENSION IF NOT EXISTS pg_trgm;\s*", "",
                              (ROOT / "db" / "01_schema.sql").read_text(encoding="utf-8"), count=1)
                cursor.execute(base)
                cursor.execute((ROOT / "db" / "02_model.sql").read_text(encoding="utf-8"))
        except BaseException:
            cls._cleanup()
            raise

    @classmethod
    def _cleanup(cls):
        try:
            with cls.connection.cursor() as cursor:
                cursor.execute(cls.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    cls.sql.Identifier(cls.schema)))
        finally:
            cls.connection.close()
            cls.temp_dir.cleanup()

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    @classmethod
    def api_connection(cls):
        from psycopg.rows import dict_row
        return cls.psycopg.connect(os.getenv("DATABASE_URL") or "", row_factory=dict_row,
                                  options=f"-c search_path={cls.schema},public", connect_timeout=5)

    def setUp(self):
        # Todos os objetos pertencem exclusivamente ao schema temporario de testes.
        with self.connection.cursor() as cursor:
            cursor.execute("TRUNCATE servidores, lotes_importacao RESTART IDENTITY")

    def test_staged_100_then_1000_are_idempotent_and_api_reads_real_rows(self):
        sample100 = self.make_sample(self.file, "aposentados", max_rows=100)
        sample1000 = self.make_sample(self.file, "aposentados", max_rows=1000)
        first = self.import_sample(self.connection, sample100)
        second = self.import_sample(self.connection, sample1000)
        repeated = self.import_sample(self.connection, sample1000)
        self.assertEqual((first["importadas"], second["importadas"],
                          repeated["importadas"]), (100, 900, 0))
        self.assertEqual(repeated["ja_existentes"], 1000)
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*), COUNT(uf) FROM servidores")
            self.assertEqual(cursor.fetchone(), (1000, 0))
            cursor.execute("SELECT estado, linhas_lidas, linhas_importadas, "
                           "linhas_descartadas FROM lotes_importacao ORDER BY id")
            self.assertEqual(cursor.fetchall(), [
                ("concluido", 100, 100, 0),
                ("concluido", 1000, 900, 100),
                ("concluido", 1000, 0, 1000),
            ])
        with patch("app.routes.connect_db", side_effect=self.api_connection):
            response = self.client.get("/api/servidores?nome=Pessoa%200000")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["pagination"]["total"], 1)
            self.assertEqual(response.json["items"][0]["nome"], "Pessoa 0000")
            self.assertIsNone(response.json["items"][0]["uf"])

    def test_carreiras_populates_uf_and_is_searchable(self):
        file = Path(self.temp_dir.name) / "carreiras.txt"
        file.write_text(
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência\n"
            + "".join(f"Servidor {n:04d};Analista;RS;Universidade;05/2026\n"
                      for n in range(100)),
            encoding="utf-8",
        )
        sample = self.make_sample(file, "carreiras")
        report = self.import_sample(self.connection, sample)
        self.assertEqual(report["importadas"], 100)
        self.assertEqual(sample.competence, "2026-05-01")
        with patch("app.routes.connect_db", side_effect=self.api_connection):
            response = self.client.get("/api/servidores?cargo=Analista&uf=RS")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["pagination"]["total"], 100)
            self.assertTrue(all(row["uf"] == "RS" for row in response.json["items"]))

    def test_failed_insert_rolls_back_batch_atomically(self):
        sample = self.make_sample(self.file, "aposentados", max_rows=100)
        row = list(sample.rows[0])
        row[3] = "X9"
        from dataclasses import replace
        broken = replace(sample, rows=(tuple(row),))
        with self.assertRaises(self.psycopg.errors.CheckViolation):
            self.import_sample(self.connection, broken)
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM lotes_importacao")
            self.assertEqual(cursor.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
