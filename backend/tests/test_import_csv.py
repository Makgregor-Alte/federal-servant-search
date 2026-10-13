import unittest
from pathlib import Path
import importlib.util
from types import SimpleNamespace

script_path = Path(__file__).resolve().parents[2] / "db" / "import_csv.py"
spec = importlib.util.spec_from_file_location("import_csv", script_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CsvTests(unittest.TestCase):
    def args(self, **kwargs):
        defaults = dict(name_column="Nome", position_column="Cargo", agency_column="Órgão",
                        uf_column="UF", id_column=None, source="carreira")
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_record_and_deterministic_identifier(self):
        row = {"Nome": "Maria Silva", "Cargo": "Analista", "Órgão": "Universidade", "UF": "RS"}
        record = module.record_from_row(row, self.args())
        self.assertEqual(record[0:5], ("Maria Silva", "Analista", "Universidade", "RS", "carreira"))
        self.assertEqual(record[5], module.record_from_row(dict(row), self.args())[5])

    def test_discard_empty_name(self):
        self.assertIsNone(module.record_from_row({"Nome": "   "}, self.args()))

    def test_invalid_uf_is_null_not_fabricated(self):
        row = {"Nome": "Maria", "Cargo": "Técnica", "Órgão": "Universidade", "UF": "ZZ"}
        self.assertIsNone(module.record_from_row(row, self.args())[3])
        row["UF"] = ""
        self.assertIsNone(module.record_from_row(row, self.args())[3])

    def test_optional_missing_fields(self):
        row = {"Nome": "Ana"}
        record = module.record_from_row(row, self.args(position_column=None, agency_column=None, uf_column=None))
        self.assertEqual(record[1:4], ("", "", None))


if __name__ == "__main__":
    unittest.main()
