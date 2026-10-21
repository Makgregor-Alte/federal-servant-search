import json
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api_client import ApiError, build_query, fetch_servants, normalize_url, validate_payload


class Response:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit=None):
        return self.data


VALID = {
    "items": [{"id": 1, "nome": "MARIA SILVA", "cargo": "Analista", "orgao": "ABC", "uf": "RS", "fonte": "Carreiras"}],
    "pagination": {"page": 1, "page_size": 20, "total": 1, "pages": 1},
}


class ClientTests(unittest.TestCase):
    def test_normalizes_root_url(self):
        self.assertEqual(normalize_url(" http://127.0.0.1:8081/ "), "http://127.0.0.1:8081")

    def test_rejects_urls_with_credentials_or_path(self):
        for url in ("file:///abc", "http://host/a", "http://user:pw@host", "http://host/?a=1", ""):
            with self.subTest(url=url), self.assertRaises(ApiError):
                normalize_url(url)

    def test_exact_filters(self):
        data = build_query({"name": "Maria Silva", "name_mode": "exact", "position": "", "agency": "", "uf": "rs", "page_size": "20"}, 2)
        self.assertEqual(data["name_mode"], "exact")
        self.assertEqual(data["uf"], "RS")
        self.assertEqual(data["page"], 2)

    def test_similar_filters(self):
        data = build_query({"name": "Mariana", "name_mode": "similar", "page_size": "10"}, 1)
        self.assertEqual(data["name_mode"], "similar")

    def test_wildcard_filters(self):
        data = build_query({"name": "%MARIA%SILVA%", "name_mode": "pattern", "page_size": "100"}, 1)
        self.assertEqual(data["name_mode"], "pattern")
        self.assertEqual(data["name"], "%MARIA%SILVA%")

    def test_combination_of_filters(self):
        data = build_query({"position": "professor", "agency": "universidade", "uf": "RS", "page_size": 50}, 1)
        self.assertEqual((data["position"], data["agency"], data["uf"]), ("professor", "universidade", "RS"))

    def test_requires_a_filter(self):
        with self.assertRaises(ApiError):
            build_query({"page_size": 20}, 1)

    def test_rejects_bad_pattern(self):
        with self.assertRaises(ApiError):
            build_query({"name": "%%%", "name_mode": "pattern", "page_size": 20}, 1)

    def test_rejects_out_of_range_page(self):
        with self.assertRaises(ApiError):
            build_query({"uf": "RS", "page_size": 20}, 0)

    def test_fetch_success_and_url(self):
        captured = {}

        def opener(req, timeout):
            captured["url"] = req.full_url
            captured["timeout"] = timeout
            return Response(json.dumps(VALID).encode())

        result = fetch_servants("http://127.0.0.1:8081", {"uf": "RS", "page_size": 20}, opener=opener)
        self.assertEqual(result, VALID)
        self.assertEqual(parse_qs(urlsplit(captured["url"]).query)["uf"], ["RS"])
        self.assertEqual(captured["timeout"], 20)

    def test_429_has_friendly_error(self):
        def opener(req, timeout):
            raise HTTPError(req.full_url, 429, "too many", {}, None)
        with self.assertRaisesRegex(ApiError, "Aguarde"):
            fetch_servants("http://127.0.0.1:8081", {"uf": "RS", "page_size": 20}, opener=opener)

    def test_504_has_friendly_error(self):
        def opener(req, timeout):
            raise HTTPError(req.full_url, 504, "gateway timeout", {}, None)
        with self.assertRaisesRegex(ApiError, "tempo"):
            fetch_servants("http://127.0.0.1:8081", {"uf": "RS", "page_size": 20}, opener=opener)

    def test_connection_error(self):
        def opener(req, timeout):
            raise URLError("unreachable")
        with self.assertRaisesRegex(ApiError, "Não foi possível"):
            fetch_servants("http://127.0.0.1:8081", {"uf": "RS", "page_size": 20}, opener=opener)

    def test_invalid_json(self):
        with self.assertRaisesRegex(ApiError, "JSON inválida"):
            fetch_servants("http://127.0.0.1:8081", {"uf": "RS", "page_size": 20}, opener=lambda req, timeout: Response(b"no"))

    def test_invalid_response(self):
        bad = {**VALID, "pagination": {"page": 3, "page_size": 20, "total": 1, "pages": 1}}
        with self.assertRaisesRegex(ApiError, "paginação inconsistente"):
            validate_payload(bad, 1, 20)

    def test_empty_page(self):
        empty = {"items": [], "pagination": {"page": 1, "page_size": 20, "total": 0, "pages": 0}}
        self.assertEqual(validate_payload(empty, 1, 20), empty)


if __name__ == "__main__":
    unittest.main()
