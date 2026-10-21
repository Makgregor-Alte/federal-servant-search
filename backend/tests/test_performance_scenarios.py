"""Offline tests for performance scenarios and HTTP contract checks."""

from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from performance_scenarios import CASES, validate_search_response


class PerformanceScenarioTests(unittest.TestCase):
    def setUp(self):
        self.valid = {"items": [], "pagination": {"page": 1, "page_size": 20, "total": 0, "pages": 0}}

    def test_all_search_filters_are_covered(self):
        self.assertEqual({case.label for case in CASES}, {"exact", "similar", "position", "agency", "state", "combined"})
        self.assertTrue(all(case.params for case in CASES))
        self.assertTrue(all(key != "name" for case in CASES for key, _ in case.params))

    def test_empty_database_is_valid_http_200(self):
        self.assertEqual(validate_search_response(200, self.valid), "ok")

    def test_positive_total_and_full_metadata(self):
        payload = {"items": [{"nome": "Teste"}], "pagination": {"page": 1, "page_size": 2, "total": 3, "pages": 2}}
        self.assertEqual(validate_search_response(200, payload), "ok")

    def test_incorrect_page_count_rejected(self):
        self.valid["pagination"]["total"] = 5
        self.valid["pagination"]["pages"] = 0
        with self.assertRaises(ValueError):
            validate_search_response(200, self.valid)

    def test_invalid_data_types_rejected(self):
        for field, val in (("total", True), ("page_size", "20"), ("pages", -1)):
            payload = {"items": [], "pagination": dict(self.valid["pagination"], **{field: val})}
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_search_response(200, payload)

    def test_unknown_status_rejected_including_5xx(self):
        for status in (400, 404, 503, 504):
            with self.subTest(status=status), self.assertRaises(ValueError):
                validate_search_response(status, {"error": "unknown"})

    def test_rate_limit_only_expected_in_overload(self):
        payload = {"error": "rate_limited", "message": "Excesso de requisicoes"}
        self.assertEqual(validate_search_response(429, payload, overload=True), "limited")
        with self.assertRaises(ValueError):
            validate_search_response(429, payload, overload=False)
        with self.assertRaises(ValueError):
            validate_search_response(429, {"error": "oops"}, overload=True)

    def test_bad_payload_or_missing_fields_rejected(self):
        for payload in ([], {"items": {}}, {"pagination": {}}, {"items": [1], "pagination": self.valid["pagination"]}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate_search_response(200, payload)


if __name__ == "__main__":
    unittest.main()
