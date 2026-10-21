"""HTTP contract checks with a simulated server."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("runtime_frontend_contract", ROOT / "scripts/check_runtime.py")
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def mock_responses():
    empty20 = json.dumps({"items": [], "pagination": {"page": 1, "page_size": 20, "total": 0, "pages": 0}}).encode()
    empty10 = json.dumps({"items": [], "pagination": {"page": 1, "page_size": 10, "total": 0, "pages": 0}}).encode()
    return [
        (200, "text/html", b"<!doctype html><html></html>"),
        (200, "application/json", b'{"status":"ok","database":"ok"}'),
        (200, "application/json", empty20),
        (400, "application/json", b'{"error":"invalid_parameters"}'),
        (200, "application/json", empty20),
        *[(200, "application/json", empty10) for _ in range(3)],
    ]


class FrontendLiveContractTests(unittest.TestCase):
    def test_extended_contract_supports_empty_database(self):
        with patch.object(RUNTIME, "request", side_effect=mock_responses()):
            summary = RUNTIME.check_contract()
        self.assertEqual(summary, {"checks": 8, "total_records": 0})

    def test_extended_contract_detects_malformed_search_results(self):
        responses = mock_responses()
        responses[-1] = (200, "application/json", b'{"items":[],"pagination":{"page":1,"page_size":10,"total":2,"pages":0}}')
        with patch.object(RUNTIME, "request", side_effect=responses):
            with self.assertRaisesRegex(RUNTIME.RuntimeCheckError, "paginação inconsistentes"):
                RUNTIME.check_contract()


if __name__ == "__main__":
    unittest.main()
