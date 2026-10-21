"""Aceitação opcional: esquema isolado, PostgreSQL real e API Flask."""

import os
import re
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


@unittest.skipUnless(os.getenv("RUN_DB_INTEGRATION_TESTS") == "1", "requires PostgreSQL")
class RealDatabaseAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        from app import create_app

        from db.acceptance import collect_snapshot, evaluate_snapshot
        cls.psycopg = psycopg
        cls.sql = sql
        cls.dict_row = dict_row
        cls.collect_snapshot = staticmethod(collect_snapshot)
        cls.evaluate_snapshot = staticmethod(evaluate_snapshot)
        cls.schema = "test_db_acceptance_" + uuid.uuid4().hex[:12]
        cls.connection = psycopg.connect(os.getenv("DATABASE_URL") or "",
                                         autocommit=True, connect_timeout=5)
        try:
            with cls.connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
                if cursor.fetchone() is None:
                    raise AssertionError("Extensao pg_trgm ausente no banco de testes")
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
                cursor.execute(sql.SQL("SET search_path TO {}, public").format(
                    sql.Identifier(cls.schema)))
                for script in ("01_schema.sql", "02_model.sql", "03_integrity.sql",
                               "04_indexes.sql"):
                    ddl = (ROOT / "db" / script).read_text("utf-8")
                    if script == "01_schema.sql":
                        ddl = re.sub(r"CREATE EXTENSION IF NOT EXISTS pg_trgm;\s*", "",
                                     ddl, count=1)
                    cursor.execute(ddl)
                # Confirma a reaplicação das migrações sem recriar a tabela principal.
                for script in ("02_model.sql", "03_integrity.sql", "04_indexes.sql"):
                    cursor.execute((ROOT / "db" / script).read_text("utf-8"))
                for fonte, nome, hash_value, uf in (
                    ("carreiras", "Servidor Teste", "a" * 64, "RS"),
                    ("aposentados", "Aposentado Teste", "b" * 64, None),
                ):
                    cursor.execute(
                        "INSERT INTO lotes_importacao "
                        "(fonte, nome_arquivo, competencia, sha256, estado, "
                        "linhas_lidas, linhas_importadas) "
                        "VALUES (%s, %s, DATE '2026-05-01', %s, 'concluido', 1, 1) RETURNING id",
                        (fonte, fonte + ".csv", hash_value),
                    )
                    batch_id = cursor.fetchone()[0]
                    cursor.execute(
                        "INSERT INTO servidores "
                        "(nome, cargo, orgao, uf, fonte, id_origem, competencia, lote_importacao_id) "
                        "VALUES (%s, %s, %s, %s, %s, %s, DATE '2026-05-01', %s)",
                        (nome, "Analista", "Universidade Federal", uf, fonte,
                         "linha-01", batch_id),
                    )
            cls.app = create_app()
            cls.app.testing = True
            cls.client = cls.app.test_client()
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

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    @classmethod
    def api_connection(cls):
        return cls.psycopg.connect(
            os.getenv("DATABASE_URL") or "", row_factory=cls.dict_row,
            options=f"-c search_path={cls.schema},public", connect_timeout=5,
        )

    def test_schema_indexes_sources_and_provenance(self):
        snapshot = self.collect_snapshot(self.connection)
        result = self.evaluate_snapshot(snapshot, file_hashes={
            "carreiras": "a" * 64, "aposentados": "b" * 64,
        })
        self.assertEqual(result["status"], "aprovado", result)
        self.assertEqual(result["registros_por_fonte"],
                         {"aposentados": 1, "carreiras": 1})
        self.assertEqual(result["lotes_concluidos_por_fonte"],
                         {"aposentados": 1, "carreiras": 1})

    def test_http_queries_read_the_isolated_database(self):
        with patch("app.routes.connect_db", side_effect=self.api_connection):
            status = self.client.get("/api/health")
            self.assertEqual(status.status_code, 200)
            total = self.client.get("/api/servidores?limit=5")
            self.assertEqual(total.status_code, 200)
            self.assertEqual(total.json["pagination"]["total"], 2)
            uf = self.client.get("/api/servidores?cargo=Analista&uf=RS")
            self.assertEqual(uf.status_code, 200)
            self.assertEqual(uf.json["pagination"]["total"], 1)
            self.assertEqual(uf.json["items"][0]["fonte"], "carreiras")

    def test_invalid_uf_and_duplicate_record_are_rejected(self):
        with self.assertRaises(self.psycopg.errors.CheckViolation):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO servidores (nome, fonte, id_origem, uf) "
                    "VALUES ('Teste', 'carreiras', 'uf-invalida', 'ZZ')"
                )
        with self.assertRaises(self.psycopg.errors.UniqueViolation):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO servidores (nome, fonte, id_origem) "
                    "VALUES ('Outro', 'carreiras', 'linha-01')"
                )


if __name__ == "__main__":
    unittest.main()
