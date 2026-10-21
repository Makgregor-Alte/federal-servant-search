"""Regressao para arquivos oficiais com linhas CSV anormalmente longas."""

import contextlib
import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

DB_DIR = Path(__file__).resolve().parents[2] / "db"
sys.path.insert(0, str(DB_DIR))
from csv_limits import MAX_PARSER_FIELD, MAX_RECORD_FIELD, configure_csv_field_limit
from import_bulk import main as bulk_main
from import_bulk import run_bulk, resolve_competence
from inspect_source import inspect
from normalize import CSVReadFailure, analyze, iter_normalized


class OfficialCSVLimitsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.file = Path(folder.name) / "aposentados.csv"

    def write(self, lines):
        self.file.write_text("Nome;Cargo;Orgao\n" + lines, encoding="utf-8")

    def test_field_beyond_python_default_is_reported_not_imported(self):
        self.write("Maria;\"" + "X" * 150_000 + "\";Universidade\n"
                   "Joao;Docente;Instituto\n")
        result = analyze(self.file, "aposentados", max_rows=100)
        self.assertEqual((result["aceitas"], result["rejeitadas"]), (1, 1))
        self.assertEqual(result["ocorrencias"], {"campo_excessivo": 1})
        report = run_bulk(self.file, "aposentados", competence="2026-05")
        self.assertEqual(report["aceitas"], 1)
        self.assertEqual(report["rejeitadas"], 1)
        self.assertEqual(report["linhas_suspeitas"], [2])
        self.assertEqual(len(list(iter_normalized(self.file, "aposentados"))), 2)

    def test_import_refuses_suspect_fields_before_any_db_write(self):
        self.write('Maria;"' + 'X' * 150_000 + '";Universidade\n')
        connection = Mock(autocommit=True)
        with self.assertRaisesRegex(CSVReadFailure, "linha fisica 2"):
            run_bulk(self.file, "aposentados", competence="2026-05",
                     connection=connection)
        connection.transaction.assert_not_called()

    def test_record_spanning_excessive_physical_lines_is_rejected(self):
        self.write('Maria;"' + 'X\n' * 17 + '";Universidade\n'
                   'Joao;Docente;Instituto\n')
        summary = analyze(self.file, "aposentados")
        self.assertEqual(summary["aceitas"], 1)
        self.assertEqual(summary["rejeitadas"], 1)
        self.assertEqual(summary["ocorrencias"], {"registro_multilinha_excessivo": 1})

    def test_short_quoted_multiline_field_stays_valid(self):
        self.write('Maria;"Docente\nFederal";Universidade\n')
        summary = analyze(self.file, "aposentados")
        self.assertEqual((summary["aceitas"], summary["rejeitadas"]), (1, 0))

    def test_inspector_does_not_approve_suspicious_sample(self):
        self.write('Maria;"' + 'X' * 150_000 + '";Universidade\n')
        report = inspect(self.file, "aposentados", sample_rows=1)
        self.assertFalse(report["ready_for_mapping"])
        self.assertEqual(report["sample_rows_with_wrong_width"], 1)
        self.assertNotIn('Maria', str(report))

    def test_sample_limit_does_not_read_next_malformed_record(self):
        self.write('Joao;Docente;Instituto\n' + 'Maria;"Sem fechamento;Universidade\n')
        result = analyze(self.file, "aposentados", max_rows=1)
        self.assertEqual(result["linhas_analisadas"], 1)

    def test_parser_uses_bounded_limit(self):
        with patch("csv.field_size_limit", side_effect=[131072, MAX_PARSER_FIELD]) as setter:
            configure_csv_field_limit()
        self.assertEqual(setter.call_args_list[-1].args, (MAX_PARSER_FIELD,))
        self.assertLess(MAX_RECORD_FIELD, MAX_PARSER_FIELD)

    def test_reader_recovers_from_parser_limit_without_leaking_personal_data(self):
        self.write('Joao;"' + 'X' * 200 + '";Universidade\n'
                   'Maria;Docente;Instituto\n')
        with patch("normalize.configure_csv_field_limit"):
            original = csv.field_size_limit()
            try:
                csv.field_size_limit(100)
                result = run_bulk(self.file, "aposentados")
            finally:
                csv.field_size_limit(original)
        self.assertEqual((result["aceitas"], result["rejeitadas"]), (1, 1))
        self.assertEqual(result["linhas_suspeitas"], [2])
        self.assertEqual(result["ocorrencias"], {"erro_csv": 1})
        self.assertNotIn("Joao", str(result))

    def test_import_refuses_parser_error_before_database_write(self):
        self.write('Joao;"' + 'X' * 200 + '";Universidade\n')
        connection = Mock(autocommit=True)
        with patch("normalize.configure_csv_field_limit"):
            original = csv.field_size_limit()
            try:
                csv.field_size_limit(100)
                with self.assertRaisesRegex(CSVReadFailure, "linha fisica 2"):
                    run_bulk(self.file, "aposentados", connection=connection)
            finally:
                csv.field_size_limit(original)
        connection.transaction.assert_not_called()

    def test_unclosed_quote_does_not_consume_every_following_row(self):
        self.write('A;Docente;Universidade\n'
                   'B;"Inicio sem fim;Instituto\n'
                   + ('fragmento de campo\n' * 18)
                   + 'C;Analista;Ministério\n'
                   + 'D;Pesquisadora;Instituto\n')
        result = run_bulk(self.file, "aposentados")
        self.assertEqual(result["aceitas"], 3)
        self.assertEqual(result["erros_estruturais"], 1)
        self.assertGreater(result["linhas_fisicas_descartadas"], 16)
        self.assertEqual(result["linhas_suspeitas"], [3])

    def test_explicit_structural_limit_is_required_for_import(self):
        self.write('A;Docente;Universidade\n'
                   'B;"Inicio sem fim;Instituto\n'
                   + ('fragmento\n' * 18)
                   + 'C;Analista;Ministério\n')
        with self.assertRaises(CSVReadFailure):
            resolve_competence(self.file, "aposentados", competence="2026-05")
        self.assertEqual(resolve_competence(self.file, "aposentados",
                                           competence="2026-05",
                                           max_structural_errors=1), "2026-05")

    def test_oversized_physical_line_does_not_halt_validation(self):
        self.write('A;' + 'X' * (300 * 1024) + ';Universidade\n'
                   'B;Docente;Instituto\n')
        result = run_bulk(self.file, "aposentados")
        self.assertEqual((result["aceitas"], result["rejeitadas"]), (1, 1))
        self.assertEqual(result["ocorrencias"], {"linha_fisica_excessiva": 1})


if __name__ == "__main__":
    unittest.main()
