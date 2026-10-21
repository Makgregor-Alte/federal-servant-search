"""Testes do fluxo de preparacao das duas fontes oficiais."""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from prepare_official_data import (
    PreparationError, docker_command, main, check_source_files, run_pipeline,
    source_filenames,
)


class OfficialImportPreparationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        names = source_filenames("2026-05")
        self.aposentados = self.folder / names["aposentados"]
        self.carreiras = self.folder / names["carreiras"]
        self.aposentados.write_text(
            "Nome;Cargo;Nome do órgão;CPF\n"
            "José da Silva;Docente;Universidade;000.111\n",
            encoding="utf-8-sig",
        )
        self.carreiras.write_text(
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência;CPF\n"
            "Maria Souza;Técnica;RS;Instituto;05/2026;000.222\n",
            encoding="cp1252",
        )

    def test_realistic_official_layouts_pass_check_source_files(self):
        self.aposentados.write_bytes((
            "Nome;CPF;Matricula;Orgao;Sigla Orgao;Orgao vinculacao;Cargo emprego\n"
            "Pessoa A;***;001;Universidade;UF;Órgão Central;Docente\n"
        ).encode("cp1252"))
        self.carreiras.write_bytes((
            "CARREIRA.052026\n"
            "Nome;CPF;Código da carreira;Descrição do cargo emprego;"
            "UF da UPAG de vinculação;Denominação do órgão de atuação;"
            "Mês de referência;Valor da remuneração;\n"
            "Pessoa B;***;001;Técnico;RS;Ministério;05;1.234,56;\n"
        ).encode("cp1252"))
        result = check_source_files(self.folder, "2026-05")
        self.assertEqual(result["fontes"]["aposentados"]["amostra"]["aceitas"], 1)
        self.assertEqual(result["fontes"]["carreiras"]["amostra"]["aceitas"], 1)
        self.assertNotIn("Pessoa A", str(result))
        self.assertNotIn("Pessoa B", str(result))

    def test_career_preamble_of_wrong_month_fails_check_source_files(self):
        self.carreiras.write_bytes((
            "CARREIRA.042026\n"
            "Nome;Descrição do cargo emprego;UF da UPAG de vinculação;"
            "Denominação do órgão de atuação;Mês de referência\n"
            "Pessoa B;Técnico;RS;Ministério;04\n"
        ).encode("cp1252"))
        with self.assertRaisesRegex(PreparationError, "diverge"):
            check_source_files(self.folder, "2026-05")

    def test_filename_pairs_are_strict(self):
        self.assertEqual(source_filenames("2026-05"), {
            "aposentados": "APOSENTADOS_052026_FULL.csv",
            "carreiras": "CARREIRA_052026.txt",
        })
        for month in ("2026-0", "2026-13", "26-05", "1975-01", "2026-00"):
            with self.subTest(month=month), self.assertRaises(PreparationError):
                source_filenames(month)

    def test_inspection_is_readonly_and_skips_personal_data(self):
        with patch("prepare_official_data._run") as runner:
            result = run_pipeline(self.folder, "2026-05")
        runner.assert_not_called()
        self.assertEqual(result["modo"], "inspecao")
        self.assertEqual(set(result["fontes"]), {"aposentados", "carreiras"})
        self.assertEqual(result["fontes"]["aposentados"]["amostra"]["aceitas"], 1)
        self.assertIn("uf", result["fontes"]["carreiras"]["campos"])
        for forbidden in ("José da Silva", "Maria Souza", "000.111", "000.222"):
            self.assertNotIn(forbidden, str(result))

    def test_missing_full_file_aborts_even_if_increment_exists(self):
        self.aposentados.rename(self.folder / "APOSENTADOS_052026.csv")
        with self.assertRaisesRegex(PreparationError, "APOSENTADOS_052026_FULL.csv"):
            check_source_files(self.folder, "2026-05")

    def test_wrong_month_in_careers_aborts(self):
        self.carreiras.write_text(
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência\n"
            "Ana;Técnica;RS;Instituto;04/2026\n", encoding="utf-8",
        )
        with self.assertRaisesRegex(PreparationError, "diverge"):
            check_source_files(self.folder, "2026-05")

    def test_invalid_month_value_aborts(self):
        self.carreiras.write_text(
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência\n"
            "Ana;Técnica;RS;Instituto;13/2026\n", encoding="utf-8",
        )
        with self.assertRaisesRegex(PreparationError, "invalida"):
            check_source_files(self.folder, "2026-05")

    def test_import_requires_confirmation_before_any_io(self):
        with patch("prepare_official_data._run") as runner:
            with self.assertRaisesRegex(PreparationError, "--confirm"):
                run_pipeline(self.folder, "2026-05", mode="import")
        runner.assert_not_called()

    def test_docker_commands_are_argv_not_shell_and_are_readonly_mounts(self):
        cmd = docker_command(self.folder, "aposentados", "2026-05")
        self.assertTrue(all(isinstance(value, str) for value in cmd))
        self.assertTrue(any(part.endswith(":ro") for part in cmd))
        self.assertNotIn("--apply", cmd)
        self.assertIn("/dados/APOSENTADOS_052026_FULL.csv", cmd)
        self.assertEqual(cmd[0:2], ["docker", "compose"])
        cmd2 = docker_command(self.folder, "carreiras", "2026-05", apply=True)
        self.assertIn("--apply", cmd2)
        self.assertIn("/dados/CARREIRA_052026.txt", cmd2)

    def test_validation_runs_both_without_writes(self):
        commands = []
        with patch("prepare_official_data._run", side_effect=lambda cmd: commands.append(cmd)):
            result = run_pipeline(self.folder, "2026-05", mode="validate")
        self.assertEqual(result["modo"], "validacao_completa")
        self.assertEqual(len(commands), 2)
        self.assertFalse(any("--apply" in cmd for cmd in commands))

    def test_import_validates_both_before_first_write(self):
        calls = []
        with patch("prepare_official_data._run", side_effect=lambda cmd: calls.append(cmd)):
            with patch("prepare_official_data._check_database", side_effect=lambda: calls.append(["db-ready"])):
                result = run_pipeline(self.folder, "2026-05", mode="import", confirm=True)
        self.assertEqual(result["modo"], "importacao_executada")
        self.assertEqual(len(calls), 5)
        self.assertFalse(any("--apply" in x for x in calls[:2]))
        self.assertEqual(calls[2], ["db-ready"])
        self.assertTrue(all("--apply" in x for x in calls[3:]))

    def test_validation_failure_does_not_write(self):
        calls = []
        def failing(command):
            calls.append(command)
            if len(calls) == 2:
                raise PreparationError("Falha de validacao")
        with patch("prepare_official_data._run", side_effect=failing):
            with self.assertRaises(PreparationError):
                run_pipeline(self.folder, "2026-05", mode="import", confirm=True)
        self.assertEqual(len(calls), 2)

    def test_file_mutation_between_validation_and_write_is_detected(self):
        calls = []
        def mutate(command):
            calls.append(command)
            if len(calls) == 2:
                self.carreiras.write_text("Arquivo diferente", encoding="utf-8")
        with patch("prepare_official_data._run", side_effect=mutate):
            with patch("prepare_official_data._check_database") as check:
                with self.assertRaisesRegex(PreparationError, "alterado"):
                    run_pipeline(self.folder, "2026-05", mode="import", confirm=True)
                check.assert_not_called()
        self.assertEqual(len(calls), 2)

    def test_main_does_not_show_personal_records(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["--data-dir", str(self.folder), "--competencia", "2026-05"])
        self.assertEqual(result, 0)
        self.assertNotIn("José da Silva", output.getvalue())
        self.assertNotIn("Maria Souza", output.getvalue())


if __name__ == "__main__":
    unittest.main()
