"""Testes da preparação de dados, independentes de Flask e PostgreSQL."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

DB_DIR = Path(__file__).resolve().parents[2] / "db"
sys.path.insert(0, str(DB_DIR))
from normalize import (analyze, clean_text, clean_uf, iter_normalized, main,
                       normalize_row, parse_reference_month)
from source_catalog import map_headers


class NormalizeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "dados.txt"

    def put(self, text, encoding="utf-8-sig"):
        self.path.write_text(text, encoding=encoding)

    def test_unicode_and_whitespace_preserve_accents(self):
        self.assertEqual(clean_text("  Jose\u0301\t  da\nSilva  "), "José da Silva")
        self.assertEqual(clean_text("A\u200bB"), "A B")

    def test_uf_only_known_codes(self):
        self.assertEqual(clean_uf(" rs "), "RS")
        self.assertEqual(clean_uf("rj"), "RJ")
        self.assertIsNone(clean_uf("ZZ"))
        self.assertIsNone(clean_uf(None))

    def test_explicit_reference_month_formats(self):
        for item in ("202605", "2026-05", "05/2026", "2026-05-01", "01/05/2026"):
            with self.subTest(item=item):
                self.assertEqual(parse_reference_month(item), "2026-05-01")

    def test_ambiguous_or_invalid_month_not_assumed(self):
        for item in ("2026-13", "31/05/2026", "maio 2026", "2026-05-30", "2026-00", ""):
            with self.subTest(item=item):
                self.assertIsNone(parse_reference_month(item))

    def test_aposentados_keep_uf_null_and_skip_pii(self):
        fields = ["Nome", "CPF", "Matrícula do Servidor", "Cargo", "Nome do órgão"]
        mapping = map_headers(fields, "aposentados")["mapped"]
        result = normalize_row({"Nome": " Ana  São José ", "CPF": "***999",
                                "Matrícula do Servidor": "123", "Cargo": " Docente ",
                                "Nome do órgão": "Universidade Federal"}, mapping, "aposentados")
        self.assertEqual(result.record["nome"], "Ana São José")
        self.assertIsNone(result.record["uf"])
        self.assertEqual(set(result.record), {"nome", "cargo", "orgao", "uf", "fonte", "competencia"})
        self.assertNotIn("***999", str(result.record))
        self.assertNotIn("123", str(result.record))
        self.assertFalse(result.issues)

    def test_carreiras_cp1252_semicolon_and_orgao_with_delimiter(self):
        self.put('Nome;CPF;Descrição do Cargo/Emprego;UF da UPAG de vinculação;Denominação do Órgão de atuação;Mês de referência\n'
                 'José de Souza;***111;Técnico;rs;"Universidade; Pública";05/2026\n', "cp1252")
        rows = list(iter_normalized(self.path, "carreiras"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].record["orgao"], "Universidade; Pública")
        self.assertEqual(rows[0].record["uf"], "RS")
        self.assertEqual(rows[0].record["competencia"], "2026-05-01")
        self.assertFalse(rows[0].issues)

    def test_month_only_with_career_preamble_has_verified_year(self):
        self.put(
            "CARREIRA.052026\n"
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência;\n"
            "Pessoa;Analista;RS;Instituto;05;\n"
        )
        rows = list(iter_normalized(self.path, "carreiras"))
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].issues)
        self.assertEqual(rows[0].record["competencia"], "2026-05-01")
        self.assertEqual(rows[0].line_number, 3)

    def test_month_only_without_explicit_year_is_invalid(self):
        self.put(
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência\n"
            "Pessoa;Analista;RS;Instituto;05\n"
        )
        self.assertIn("competencia_invalida", list(iter_normalized(self.path, "carreiras"))[0].issues)

    def test_career_preamble_disagrees_with_row_month(self):
        self.put(
            "CARREIRA.052026\n"
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência\n"
            "Pessoa;Analista;RS;Instituto;04\n"
        )
        self.assertIn("competencia_invalida", list(iter_normalized(self.path, "carreiras"))[0].issues)

    def test_career_preamble_disagrees_with_full_date(self):
        self.put(
            "CARREIRA.052026\n"
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência\n"
            "Pessoa;Analista;RS;Instituto;2026-04\n"
        )
        self.assertIn("competencia_invalida", list(iter_normalized(self.path, "carreiras"))[0].issues)

    def test_missing_name_is_rejected_with_reason(self):
        self.put("Nome;Cargo;Nome do órgão\n;Docente;Universidade\n")
        rows = list(iter_normalized(self.path, "aposentados"))
        self.assertIsNone(rows[0].record)
        self.assertEqual(rows[0].issues, ("nome_ausente",))

    def test_wrong_width_rejected_without_leaking_row(self):
        self.put("Nome;Cargo;Nome do órgão\nMaria;Docente\nJoão;Médico;Órgão\n")
        rows = list(iter_normalized(self.path, "aposentados"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].issues, ("quantidade_colunas_invalida",))
        self.assertIsNotNone(rows[1].record)

    def test_empty_cargo_and_orgao_warn_but_keep_named_record(self):
        fields = ["Nome", "Cargo", "Nome do órgão"]
        record = normalize_row({"Nome": "Ana", "Cargo": "", "Nome do órgão": ""},
                               map_headers(fields, "aposentados")["mapped"], "aposentados")
        self.assertEqual(record.record["nome"], "Ana")
        self.assertEqual(record.issues, ("cargo_ausente", "orgao_ausente"))

    def test_carreiras_missing_or_invalid_uf_remains_null(self):
        mapping = map_headers(["Nome", "Descrição do Cargo/Emprego", "UF da UPAG de vinculação",
                               "Denominação do Órgão de atuação"], "carreiras")["mapped"]
        row = {"Nome": "Ana", "Descrição do Cargo/Emprego": "Técnica",
               "Denominação do Órgão de atuação": "Órgão", "UF da UPAG de vinculação": "ZZ"}
        result = normalize_row(row, mapping, "carreiras")
        self.assertIsNone(result.record["uf"])
        self.assertIn("uf_invalida", result.issues)
        row["UF da UPAG de vinculação"] = ""
        self.assertIn("uf_ausente", normalize_row(row, mapping, "carreiras").issues)

    def test_invalid_reference_month_tracked(self):
        mapping = map_headers(["Nome", "Descrição do Cargo/Emprego", "UF da UPAG de vinculação",
                               "Denominação do Órgão de atuação", "Mês de referência"], "carreiras")["mapped"]
        raw = {"Nome": "Ana", "Descrição do Cargo/Emprego": "Técnica",
               "UF da UPAG de vinculação": "RS", "Denominação do Órgão de atuação": "Órgão",
               "Mês de referência": "2026-16"}
        result = normalize_row(raw, mapping, "carreiras")
        self.assertIsNone(result.record["competencia"])
        self.assertIn("competencia_invalida", result.issues)

    def test_ambiguous_header_refused_before_reading_data(self):
        self.put("Nome;Cargo;Nome do órgão;Nome do orgao\nPessoa;Cargo;Órgão;Outra\n")
        with self.assertRaisesRegex(ValueError, "Layout incompatível"):
            list(iter_normalized(self.path, "aposentados"))

    def test_missing_required_column_refused(self):
        self.put("Nome;Cargo;Outra\nPessoa;Cargo;Órgão\n")
        with self.assertRaisesRegex(ValueError, "Layout incompatível"):
            list(iter_normalized(self.path, "aposentados"))

    def test_max_rows_bounded_stream(self):
        self.put("Nome;Cargo;Nome do órgão\nAna;A;Órgão\nBia;B;Órgão\nCia;C;Órgão\n")
        self.assertEqual(len(list(iter_normalized(self.path, "aposentados", max_rows=2))), 2)
        with self.assertRaisesRegex(ValueError, "max_rows"):
            list(iter_normalized(self.path, "aposentados", max_rows=0))

    def test_report_contains_aggregates_only(self):
        self.put("Nome;Cargo;Nome do órgão\nAna Particular;Docente;Órgão Particular\n;Cargo;X\n")
        summary = analyze(self.path, "aposentados")
        self.assertEqual((summary["linhas_analisadas"], summary["aceitas"],
                          summary["rejeitadas"]), (2, 1, 1))
        self.assertEqual(summary["ocorrencias"], {"nome_ausente": 1})
        self.assertNotIn("Ana Particular", json.dumps(summary, ensure_ascii=False))
        self.assertNotIn("Órgão Particular", json.dumps(summary, ensure_ascii=False))

    def test_cli_json_and_status_do_not_leak_data(self):
        self.put("Nome;Cargo;Nome do órgão\nAna Particular;Docente;Órgão Particular\n")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status = main(["--file", str(self.path), "--source", "aposentados"])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout.getvalue())["aceitas"], 1)
        self.assertNotIn("Ana Particular", stdout.getvalue())

    def test_cli_returns_nonzero_for_rejected_lines(self):
        self.put("Nome;Cargo;Nome do órgão\n;A;B\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--file", str(self.path), "--source", "aposentados"]), 1)

    def test_cli_rejects_bad_layout_without_details(self):
        self.put("Nome;Cargo;Setor\nAna;A;B\n")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(main(["--file", str(self.path), "--source", "aposentados"]), 2)
        self.assertIn("layout inválido", stderr.getvalue())

    def test_all_republic_units(self):
        valid = "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
        self.assertEqual({clean_uf(uf.lower()) for uf in valid}, set(valid))


if __name__ == "__main__":
    unittest.main()
