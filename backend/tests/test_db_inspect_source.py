import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

DB_DIR = Path(__file__).resolve().parents[2] / "db"
sys.path.insert(0, str(DB_DIR))
from inspect_source import inspect, main


class SourceInspectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "fixture.csv"

    def test_carreiras_cp1252_semicolon_and_private_values_never_printed(self):
        self.path.write_bytes((
            "Nome;CPF;Descrição do Cargo/Emprego;UF da UPAG de vinculação;Denominação do Órgão de atuação\n"
            'Maria Teste;***123456**;Analista;RS;"Órgão; fictício"\n'
        ).encode("cp1252"))
        report = inspect(self.path, "carreiras")
        self.assertEqual(report["encoding"], "cp1252")
        self.assertEqual(report["delimiter"], ";")
        self.assertTrue(report["ready_for_mapping"])
        self.assertEqual(report["sample_rows_checked"], 1)
        self.assertNotIn("Maria Teste", json.dumps(report))
        self.assertNotIn("***123456**", json.dumps(report))

    def test_aposentados_utf8_bom_and_commas(self):
        self.path.write_text('Nome,Nome do órgão,Cargo\nAna Teste,Universidade,Docente\n', encoding="utf-8-sig")
        report = inspect(self.path, "aposentados")
        self.assertEqual(report["encoding"], "utf-8-sig")
        self.assertTrue(report["ready_for_mapping"])
        self.assertEqual(report["unavailable_in_source"], ["uf"])

    def test_wrong_width_is_reported_without_values(self):
        self.path.write_text('Nome;Nome do órgão;Cargo\nAna;Órgão\n', encoding="utf-8")
        report = inspect(self.path, "aposentados")
        self.assertEqual(report["sample_rows_with_wrong_width"], 1)
        self.assertFalse(report["ready_for_mapping"])

    def test_unknown_headers_are_not_claimed_compatible(self):
        self.path.write_text('Nome;Setor;Cargo\nAna;X;Y\n', encoding="utf-8")
        report = inspect(self.path, "aposentados")
        self.assertFalse(report["ready_for_mapping"])
        self.assertIn("orgao", report["missing_required"])

    def test_cli_does_not_output_record_values(self):
        self.path.write_text('Nome;Nome do órgão;Cargo\nNome particular;X;Y\n', encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--file", str(self.path), "--source", "aposentados"]), 0)
        self.assertNotIn("Nome particular", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["sample_rows_checked"], 1)

    def test_carreiras_official_preamble_and_terminal_separator(self):
        self.path = self.path.with_suffix(".txt")
        self.path.write_bytes((
            "CARREIRA.052026\r\n"
            "Nome;CPF;Código da carreira;Descrição do cargo emprego;"
            "UF da UPAG de vinculação;Denominação do órgão de atuação;"
            "Mês de referência;Valor da remuneração;\r\n"
            "Pessoa Particular;***;001;Técnico;RS;Ministério;05;1.234,56;\r\n"
        ).encode("cp1252"))
        report = inspect(self.path, "carreiras")
        self.assertTrue(report["ready_for_mapping"])
        self.assertEqual(report["competencia_cabecalho"], "2026-05-01")
        self.assertEqual(report["sample_rows_checked"], 1)
        self.assertEqual(report["sample_rows_with_wrong_width"], 0)
        self.assertNotIn("Pessoa Particular", json.dumps(report))

    def test_terminal_separator_with_unexpected_value_is_rejected(self):
        self.path.write_text(
            "Nome;Cargo;Nome do órgão;\nAna;Docente;Universidade;EXTRA\n",
            encoding="utf-8",
        )
        report = inspect(self.path, "aposentados")
        self.assertFalse(report["ready_for_mapping"])
        self.assertEqual(report["sample_rows_with_wrong_width"], 1)

    def test_not_found_returns_nonzero(self):
        self.assertEqual(main(["--file", str(self.path), "--source", "aposentados"]), 2)

    def test_zip_is_not_accepted_as_csv(self):
        self.path = self.path.with_suffix('.zip')
        self.path.write_bytes(b'notzip')
        with self.assertRaises(ValueError):
            inspect(self.path, 'aposentados')

    def test_sample_limit(self):
        self.path.write_text('Nome;Nome do órgão;Cargo\nAna;O;A\nBia;P;B\n', encoding='utf-8')
        self.assertEqual(inspect(self.path, 'aposentados', sample_rows=1)['sample_rows_checked'], 1)
        with self.assertRaises(ValueError):
            inspect(self.path, 'aposentados', sample_rows=10001)


if __name__ == "__main__":
    unittest.main()
