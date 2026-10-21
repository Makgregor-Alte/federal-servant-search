"""Validação opcional de COPY e transações contra PostgreSQL real."""

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
class RealBulkImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        from import_bulk import run_bulk

        cls.sql = sql
        cls.run_bulk = staticmethod(run_bulk)
        cls.schema = "test_bulk_" + uuid.uuid4().hex[:16]
        cls.connection = psycopg.connect(os.getenv("DATABASE_URL") or "",
                                         autocommit=True, connect_timeout=5)
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.file = Path(cls.temp_dir.name) / "aposentados.csv"
        try:
            with cls.connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
                if not cursor.fetchone():
                    raise AssertionError("pg_trgm deve estar instalado")
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
                cursor.execute(sql.SQL("SET search_path TO {}, public").format(
                    sql.Identifier(cls.schema)))
                first = re.sub(r"CREATE EXTENSION IF NOT EXISTS pg_trgm;\s*", "",
                               (ROOT / "db" / "01_schema.sql").read_text("utf-8"), count=1)
                cursor.execute(first)
                cursor.execute((ROOT / "db" / "02_model.sql").read_text("utf-8"))
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

    def setUp(self):
        with self.connection.cursor() as cursor:
            cursor.execute("TRUNCATE servidores, lotes_importacao RESTART IDENTITY")

    def test_full_load_and_replay_across_batches(self):
        lines = ["Nome;Cargo;Nome do órgão;CPF"]
        lines.extend(f"Pessoa {i:04d};Pesquisador;Universidade;sigilo-{i}"
                     for i in range(19))
        lines.append(";Analista;Universidade;desconhecido")
        self.file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        first = self.run_bulk(self.file, "aposentados", batch_size=6,
                              competence="2026-05", connection=self.connection)
        repeated = self.run_bulk(self.file, "aposentados", batch_size=6,
                                 competence="2026-05", connection=self.connection)
        self.assertEqual((first["importadas"], first["rejeitadas"]), (19, 1))
        self.assertEqual((repeated["importadas"], repeated["ja_existentes"]), (0, 19))
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*), COUNT(uf), MIN(competencia) FROM servidores")
            count, ufs, competence = cursor.fetchone()
            self.assertEqual((count, ufs), (19, 0))
            self.assertEqual(competence.isoformat(), "2026-05-01")
            cursor.execute("SELECT estado, linhas_importadas, linhas_descartadas "
                           "FROM lotes_importacao ORDER BY id")
            self.assertEqual(cursor.fetchall(), [("concluido", 19, 1),
                                                   ("concluido", 0, 20)])

    def test_final_status_updates_are_accepted_by_postgresql(self):
        from import_bulk import BulkReport, _save_progress
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO lotes_importacao (fonte, nome_arquivo, sha256) "
                "VALUES ('carreiras', 'teste.txt', NULL) RETURNING id"
            )
            batch_id = cursor.fetchone()[0]
        report = BulkReport("carreiras", "teste.txt", "hash", "2026-05-01")
        report.lote_id = batch_id
        report.linhas_lidas = 10
        report.importadas = 9
        report.rejeitadas = 1
        _save_progress(self.connection, report, state="concluido")
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT estado, concluido_em IS NOT NULL, linhas_lidas, "
                "linhas_importadas, linhas_descartadas "
                "FROM lotes_importacao WHERE id = %s", (batch_id,)
            )
            self.assertEqual(cursor.fetchone(), ("concluido", True, 10, 9, 1))

    def test_inferred_competence_is_consistent_in_postgresql(self):
        self.file.write_text(
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência\n"
            "Ana;Analista;RS;Universidade;\n"
            "Bia;Analista;RS;Universidade;05/2026\n", encoding="utf-8")
        report = self.run_bulk(self.file, "carreiras", batch_size=1,
                               connection=self.connection)
        self.assertEqual(report["competencia"], "2026-05-01")
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*), COUNT(competencia) FROM servidores")
            self.assertEqual(cursor.fetchone(), (2, 2))
            cursor.execute(
                "SELECT COUNT(*) FROM servidores s "
                "JOIN lotes_importacao l ON l.id=s.lote_importacao_id "
                "WHERE s.competencia IS DISTINCT FROM l.competencia"
            )
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_mixed_months_do_not_create_batch_or_records(self):
        self.file.write_text(
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência\n"
            "Ana;Analista;RS;Universidade;05/2026\n"
            "Bia;Analista;RS;Universidade;06/2026\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Mais de uma competencia"):
            self.run_bulk(self.file, "carreiras", batch_size=1,
                          connection=self.connection)
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM servidores")
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT COUNT(*) FROM lotes_importacao")
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_failed_batch_rolls_back_and_reimport_finishes(self):
        self.file.write_text(
            "Nome;Cargo;Nome do órgão\n"
            "Ana;Analista;Universidade\n"
            "Bia;Analista;Universidade\n"
            "BLOQUEADO;Analista;Universidade\n"
            "Duda;Analista;Universidade\n", encoding="utf-8")
        with self.connection.cursor() as cursor:
            cursor.execute("ALTER TABLE servidores ADD CONSTRAINT teste_bloqueio "
                           "CHECK (nome <> 'BLOQUEADO')")
        try:
            with self.assertRaises(Exception):
                self.run_bulk(self.file, "aposentados", batch_size=2,
                              connection=self.connection)
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM servidores")
                self.assertEqual(cursor.fetchone()[0], 2)
                cursor.execute("SELECT estado, linhas_importadas FROM lotes_importacao")
                self.assertEqual(cursor.fetchone(), ("falhou", 2))
        finally:
            with self.connection.cursor() as cursor:
                cursor.execute("ALTER TABLE servidores DROP CONSTRAINT teste_bloqueio")
        report = self.run_bulk(self.file, "aposentados", batch_size=2,
                               connection=self.connection)
        self.assertEqual((report["importadas"], report["ja_existentes"]), (2, 2))
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM servidores")
            self.assertEqual(cursor.fetchone()[0], 4)


if __name__ == "__main__":
    unittest.main()
