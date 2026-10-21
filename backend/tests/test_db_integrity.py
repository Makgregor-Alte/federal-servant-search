"""Proteção contra perdas silenciosas na deduplicação de registros."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "db"))
from import_bulk import run_bulk
from import_sample import import_sample, make_sample
from integrity import CONFLICT_MESSAGE, assert_rows_consistent, audit_connection
from test_db_bulk_import import FakeConnection


class IdentitySafetyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.file = self.directory / "aposentados.csv"
        self.connection = FakeConnection()

    def write(self, content):
        self.file.write_text("Nome;Cargo;Nome do órgão\n" + content, encoding="utf-8")

    def test_identical_file_reimport_is_idempotent(self):
        self.write("Ana;Analista;Universidade\nAna;Analista;Universidade\n")
        first = run_bulk(self.file, "aposentados", connection=self.connection,
                         competence="2026-05", batch_size=1)
        repeated = run_bulk(self.file, "aposentados", connection=self.connection,
                            competence="2026-05", batch_size=1)
        self.assertEqual((first["importadas"], repeated["importadas"]), (2, 0))
        self.assertEqual(repeated["ja_existentes"], 2)
        self.assertEqual(len(self.connection.rows), 2)  # Homônimos não são eliminados.

    def test_different_approved_competences_are_not_merged_by_name(self):
        self.write("Ana;Analista;Universidade\n")
        run_bulk(self.file, "aposentados", connection=self.connection,
                 competence="2026-05")
        self.write("Ana;Analista;Universidade\nBia;Docente;Instituto\n")
        run_bulk(self.file, "aposentados", connection=self.connection,
                 competence="2026-06")
        self.assertEqual(len(self.connection.rows), 3)
        self.assertEqual({v[-1] for v in self.connection.rows.values()},
                         {"2026-05-01", "2026-06-01"})

    def test_identical_file_different_competence_cannot_be_silently_discarded(self):
        self.write("Ana;Analista;Universidade\n")
        run_bulk(self.file, "aposentados", connection=self.connection,
                 competence="2026-05")
        with self.assertRaisesRegex(ValueError, "competencia divergentes"):
            run_bulk(self.file, "aposentados", connection=self.connection,
                     competence="2026-06")
        self.assertEqual(len(self.connection.rows), 1)
        self.assertEqual(self.connection.batches[2]["estado"], "falhou")
        self.assertEqual(self.connection.batches[2]["inserted"], 0)

    def test_tampered_existing_identity_is_detected(self):
        self.write("Ana;Analista;Universidade\n")
        run_bulk(self.file, "aposentados", connection=self.connection)
        key = next(iter(self.connection.rows))
        stored = self.connection.rows[key]
        self.connection.rows[key] = ("Nome alterado", *stored[1:])
        with self.assertRaisesRegex(ValueError, "Identificador"):
            run_bulk(self.file, "aposentados", connection=self.connection)
        self.assertEqual(len(self.connection.rows), 1)

    def test_renaming_same_file_does_not_duplicate_rows(self):
        self.write("Ana;Analista;Universidade\n")
        run_bulk(self.file, "aposentados", connection=self.connection)
        renamed = self.file.with_name("copia.csv")
        renamed.write_bytes(self.file.read_bytes())
        result = run_bulk(renamed, "aposentados", connection=self.connection)
        self.assertEqual(result["importadas"], 0)
        self.assertEqual(result["ja_existentes"], 1)

    def test_same_name_different_cargo_in_same_file_are_distinct_rows(self):
        self.write("Ana;Analista;Universidade\nAna;Docente;Instituto\n")
        result = run_bulk(self.file, "aposentados", connection=self.connection)
        self.assertEqual(result["importadas"], 2)
        self.assertEqual(len(self.connection.rows), 2)


class AuditAndSampleTests(unittest.TestCase):
    def test_sample_check_parameterized_and_rejects_collision(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        row = ("Ana", "Docente", "Órgão", "RS", "carreiras", "chave", "2026-05-01")
        with self.assertRaises(ValueError) as problem:
            assert_rows_consistent(cursor, (row,))
        self.assertEqual(str(problem.exception), CONFLICT_MESSAGE)
        sql, params = cursor.execute.call_args.args
        self.assertNotIn("Órgão", sql)
        self.assertIn("%s::date", sql)
        self.assertEqual(tuple(params), row)

    def test_sample_check_has_no_sql_for_empty_rows(self):
        cursor = MagicMock()
        assert_rows_consistent(cursor, ())
        cursor.execute.assert_not_called()

    def test_aggregate_audit_does_not_return_names_or_ids(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [("aposentados", "2026-05", 10, 10),
                                        ("carreiras", "2026-06", 8, 0)]
        cursor.fetchone.side_effect = [(0,), (2,), (1,)]
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        summary = audit_connection(connection)
        self.assertEqual(summary["registros_divergentes_do_lote"], 0)
        self.assertEqual(summary["registros_sem_lote"], 2)
        self.assertEqual(summary["lotes_com_falha"], 1)
        self.assertEqual(len(summary["fontes"]), 2)
        self.assertNotIn("nome", json.dumps(summary))
        self.assertEqual(cursor.execute.call_count, 4)

    def test_sample_conflict_abort_before_any_record_insert(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Path(folder) / "a.csv"
            f.write_text("Nome;Cargo;Nome do órgão\n" +
                         "\n".join(f"Pessoa {i};Analista;Universidade" for i in range(100)) +
                         "\n", encoding="utf-8")
            sample = make_sample(f, "aposentados")
            cursor = MagicMock()
            cursor.fetchone.side_effect = [(15,), (True,)]
            connection = MagicMock()
            connection.cursor.return_value.__enter__.return_value = cursor
            with self.assertRaisesRegex(ValueError, "Identificador"):
                import_sample(connection, sample)
            cursor.executemany.assert_not_called()

    def test_integrity_migration_is_safe_and_mounted(self):
        sql = (ROOT / "db" / "03_integrity.sql").read_text("utf-8")
        config = (ROOT / "docker-compose.yml").read_text("utf-8")
        self.assertIn("NOT VALID", sql)
        self.assertIn("servidores_uf_valida_ck", sql)
        self.assertIn("servidores_id_origem_preenchido_ck", sql)
        self.assertNotIn("DROP TABLE", sql.upper())
        self.assertIn("./db/03_integrity.sql:/docker-entrypoint-initdb.d/03_integrity.sql:ro", config)


if __name__ == "__main__":
    unittest.main()
