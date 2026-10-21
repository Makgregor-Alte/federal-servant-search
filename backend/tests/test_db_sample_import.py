"""Testes de amostragem e importação, sem dependência obrigatória do banco."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

DB_DIR = Path(__file__).resolve().parents[2] / "db"
sys.path.insert(0, str(DB_DIR))
from import_sample import SAMPLE_SIZES, import_sample, main, make_sample


class SamplePreparationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / "aposentados.csv"

    def put(self, count, *, malformed=False):
        lines = ["Nome;Cargo;Nome do órgão;CPF"]
        for n in range(count):
            name = "" if malformed and n == 1 else f"Pessoa {n:05d}"
            lines.append(f"{name};Docente;Universidade;11122233344")
        self.file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_sample_sizes_respect_scanned_rows(self):
        self.put(10020)
        for n in SAMPLE_SIZES:
            with self.subTest(n=n):
                sample = make_sample(self.file, "aposentados", max_rows=n)
                self.assertEqual((sample.read, len(sample.rows), sample.rejected), (n, n, 0))
                self.assertEqual(len({row[5] for row in sample.rows}), n)

    def test_source_identity_stable_and_distinct_even_for_duplicate_name(self):
        self.put(100)
        a = make_sample(self.file, "aposentados")
        b = make_sample(self.file, "aposentados")
        self.assertEqual(a.checksum, b.checksum)
        self.assertEqual(a.rows, b.rows)
        self.assertNotEqual(a.rows[0][5], a.rows[1][5])

    def test_invalid_rows_skipped_without_pii_in_report(self):
        self.put(100, malformed=True)
        sample = make_sample(self.file, "aposentados")
        self.assertEqual((sample.read, len(sample.rows), sample.rejected), (100, 99, 1))
        self.assertEqual(sample.issues, {"nome_ausente": 1})
        text = json.dumps(sample.report())
        self.assertNotIn("11122233344", text)
        self.assertNotIn("Pessoa 00000", text)
        self.assertTrue(all(row[3] is None for row in sample.rows))

    def test_source_and_invalid_month_rejected(self):
        self.put(100)
        with self.assertRaises(ValueError):
            make_sample(self.file, "desconhecida")
        with self.assertRaises(ValueError):
            make_sample(self.file, "aposentados", competence="2026-13")
        with self.assertRaises(ValueError):
            make_sample(self.file, "aposentados", max_rows=99)

    def test_explicit_month_applies_when_not_present_in_dataset(self):
        self.put(100)
        sample = make_sample(self.file, "aposentados", competence="05/2026")
        self.assertEqual(sample.competence, "2026-05-01")
        self.assertTrue(all(row[6] == "2026-05-01" for row in sample.rows))

    def test_file_month_must_agree_with_supplied_month(self):
        self.file = self.file.with_suffix(".txt")
        self.file.write_text(
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência\n"
            "José;Docente;RS;Universidade;05/2026\n",
            encoding="utf-8",
        )
        self.assertEqual(make_sample(self.file, "carreiras").competence, "2026-05-01")
        with self.assertRaisesRegex(ValueError, "diverge"):
            make_sample(self.file, "carreiras", competence="2026-06")

    def test_inferred_month_is_applied_to_all_sample_rows(self):
        self.file = self.file.with_suffix(".txt")
        self.file.write_text(
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência\n"
            "Ana;Docente;RS;Universidade;\n"
            "Bia;Docente;RS;Universidade;05/2026\n", encoding="utf-8")
        sample = make_sample(self.file, "carreiras")
        self.assertEqual(sample.competence, "2026-05-01")
        self.assertEqual([row[6] for row in sample.rows],
                         ["2026-05-01", "2026-05-01"])

    def test_invalid_month_rejected_before_sample_import(self):
        self.file = self.file.with_suffix(".txt")
        self.file.write_text(
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência\n"
            "Ana;Docente;RS;Universidade;13/2026\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Competencia invalida"):
            make_sample(self.file, "carreiras")

    def test_two_reference_months_in_one_sample_rejected(self):
        self.file = self.file.with_suffix(".txt")
        self.file.write_text(
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência\n"
            "José;Docente;RS;Universidade;05/2026\n"
            "Ana;Docente;RS;Universidade;06/2026\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "multiplas competencias"):
            make_sample(self.file, "carreiras")

    def test_report_is_json_and_read_only_by_default(self):
        self.put(100)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(["--file", str(self.file), "--source", "aposentados"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue())["modo"], "validacao")
        self.assertNotIn("11122233344", output.getvalue())

    def test_invalid_layout_returns_sanitized_error(self):
        self.file.write_text("X;Y\nNome privado;CPF privado\n", encoding="utf-8")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main(["--file", str(self.file), "--source", "aposentados"])
        self.assertEqual(code, 2)
        self.assertNotIn("CPF privado", stderr.getvalue())

    def test_non_positive_batch_size_rejected_before_db_access(self):
        self.put(100)
        sample = make_sample(self.file, "aposentados")
        for size in (0, -1, 1001):
            with self.assertRaises(ValueError):
                import_sample(None, sample, batch_size=size)

    def test_empty_sample_must_not_create_batch(self):
        self.put(0)
        sample = make_sample(self.file, "aposentados")
        with self.assertRaisesRegex(ValueError, "nao possui"):
            import_sample(None, sample)

    def test_batch_writer_parameterizes_every_insert_and_counts_conflicts(self):
        self.put(100)
        sample = make_sample(self.file, "aposentados")
        cursor = MagicMock()
        cursor.fetchone.side_effect = [(31,), (False,)]
        cursor.rowcount = 37
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        report = import_sample(connection, sample, batch_size=100)
        self.assertEqual(report["importadas"], 37)
        self.assertEqual(report["ja_existentes"], 63)
        self.assertEqual(report["lote_id"], 31)
        sql, params = cursor.executemany.call_args.args
        self.assertIn("ON CONFLICT (fonte, id_origem) DO NOTHING", sql)
        self.assertIn("VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", sql)
        self.assertEqual(params[0][-1], 31)
        self.assertNotIn("Pessoa 00000", sql)
        connection.transaction.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
