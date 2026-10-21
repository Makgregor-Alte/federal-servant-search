"""Tests for the response shape consumed by the web search interface."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("runtime_contract", ROOT / "scripts/check_runtime.py")
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


class FrontendContractTests(unittest.TestCase):
    def data(self, items=None, total=0, page_size=20):
        return {
            "items": items if items is not None else [],
            "pagination": {
                "page": 1,
                "page_size": page_size,
                "total": total,
                "pages": (total + page_size - 1) // page_size,
            },
        }

    def test_empty_search_response(self):
        self.assertEqual(RUNTIME.validate_search_response(self.data(), requested_page=1, requested_size=20), 0)

    def test_response_with_nullable_fields(self):
        item = {"id": 1, "nome": "Ana", "cargo": None, "orgao": "FURG", "uf": None, "fonte": "aposentados"}
        self.assertEqual(RUNTIME.validate_search_response(self.data([item], total=1), requested_page=1, requested_size=20), 1)

    def test_omitted_field_is_rejected(self):
        item = {"id": 1, "nome": "Ana", "cargo": "Docente", "orgao": "FURG", "fonte": "carreiras"}
        with self.assertRaises(RUNTIME.RuntimeCheckError):
            RUNTIME.validate_search_response(self.data([item], total=1), requested_page=1, requested_size=20)

    def test_count_cannot_exceed_page_size(self):
        with self.assertRaises(RUNTIME.RuntimeCheckError):
            RUNTIME.validate_search_response(self.data([{"id": i, "nome": "Ana", "cargo": "A", "orgao": "B", "uf": "RS", "fonte": "carreiras"} for i in range(3)], total=3, page_size=2), requested_page=1, requested_size=2)

    def test_missing_pagination_or_items_is_rejected(self):
        for payload in ({"items": []}, {"pagination": {}}, []):
            with self.subTest(payload=payload), self.assertRaises(RUNTIME.RuntimeCheckError):
                RUNTIME.validate_search_response(payload, requested_page=1, requested_size=20)

    def test_page_size_and_total_consistency(self):
        for key, value in (("page_size", 21), ("total", -1), ("pages", 9), ("page", 2)):
            payload = self.data()
            payload["pagination"][key] = value
            with self.subTest(key=key), self.assertRaises(RUNTIME.RuntimeCheckError):
                RUNTIME.validate_search_response(payload, requested_page=1, requested_size=20)

    def test_types_in_records_are_validated(self):
        record = {"id": 1, "nome": "Ana", "cargo": None, "orgao": None, "uf": None, "fonte": "carreiras"}
        for key, value in (("id", True), ("nome", 1), ("uf", 10)):
            item = dict(record, **{key: value})
            with self.subTest(key=key), self.assertRaises(RUNTIME.RuntimeCheckError):
                RUNTIME.validate_search_response(self.data([item], total=1), requested_page=1, requested_size=20)


if __name__ == "__main__":
    unittest.main()
