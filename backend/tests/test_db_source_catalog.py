import importlib.util
import sys
import unittest
from pathlib import Path

DB_DIR = Path(__file__).resolve().parents[2] / "db"
sys.path.insert(0, str(DB_DIR))
from source_catalog import SOURCES, map_headers, normalized_header


class SourceCatalogTests(unittest.TestCase):
    def test_normalize_header_case_accents_spacing(self):
        self.assertEqual(normalized_header(" UF da UPAG de VINCULAÇÃO "), "ufdaupagdevinculacao")
        self.assertEqual(normalized_header("\ufeffDescrição do Cargo/Emprego"), "descricaodocargoemprego")

    def test_carreiras_dictionary_mapping(self):
        headers = ["Nome", "CPF", "Código da Carreira", "Descrição do Cargo/Emprego",
                   "UF da UPAG de vinculação", "Denominação do Órgão de atuação",
                   "Mês de referência", "Valor da Remuneração"]
        report = map_headers(headers, "carreiras")
        self.assertTrue(report["ready_for_mapping"])
        self.assertEqual(report["mapped"]["cargo"], "Descrição do Cargo/Emprego")
        self.assertEqual(report["mapped"]["uf"], "UF da UPAG de vinculação")
        self.assertEqual(report["mapped"]["orgao"], "Denominação do Órgão de atuação")

    def test_aposentados_dictionary_mapping_no_uf(self):
        headers = ["Nome", "CPF", "Nome do órgão", "Cargo", "Tipo de Aposentadoria"]
        report = map_headers(headers, "aposentados")
        self.assertTrue(report["ready_for_mapping"])
        self.assertEqual(report["unavailable_in_source"], ["uf"])
        self.assertNotIn("uf", report["mapped"])

    def test_aposentados_actual_downloaded_header_aliases(self):
        headers = ["Nome", "CPF", "Matricula", "Orgao", "Sigla Orgao",
                   "Orgao vinculacao", "Cargo emprego", "Classe", "Padrao",
                   "Referencia", "Nivel", "Tipo aposentadoria"]
        report = map_headers(headers, "aposentados")
        self.assertTrue(report["ready_for_mapping"])
        self.assertEqual(report["mapped"]["orgao"], "Orgao")
        self.assertEqual(report["mapped"]["cargo"], "Cargo emprego")
        self.assertEqual(report["mapped"]["sigla_orgao"], "Sigla Orgao")

    def test_missing_mandatory_field(self):
        report = map_headers(["Nome", "Cargo"], "aposentados")
        self.assertFalse(report["ready_for_mapping"])
        self.assertEqual(report["missing_required"], ["orgao"])

    def test_never_guess_unknown_field(self):
        report = map_headers(["Nome", "Descrição do Cargo/Emprego", "UF da UPAG de vinculação",
                              "Campo não documentado"], "carreiras")
        self.assertFalse(report["ready_for_mapping"])
        self.assertIn("Campo não documentado", report["unmapped_headers"])

    def test_ambiguity_is_detected(self):
        report = map_headers(["Nome", "Nome do aposentado", "Cargo", "Nome do órgão"], "aposentados")
        self.assertFalse(report["ready_for_mapping"])
        self.assertIn("nome", report["ambiguous"])

    def test_duplicate_normalized_headers_are_detected(self):
        report = map_headers(["Nome", "Cargo", "Nome do órgão", "Nome do orgao"], "aposentados")
        self.assertFalse(report["ready_for_mapping"])
        self.assertTrue(report["duplicate_headers"])

    def test_dictionary_sources_present(self):
        self.assertEqual(set(SOURCES), {"aposentados", "carreiras"})
        for spec in SOURCES.values():
            self.assertTrue(spec.dictionary_url.startswith("https://"))


if __name__ == "__main__":
    unittest.main()
