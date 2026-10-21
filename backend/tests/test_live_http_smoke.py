"""Optional HTTP checks against the running Gunicorn API container."""
import json
import os
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen


@unittest.skipUnless(
    os.getenv("RUN_HTTP_SMOKE_TESTS") == "1",
    "requires an already-running API service",
)
class LiveHttpSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_url = os.getenv("API_BASE_URL", "http://backend:5000").rstrip("/")

    def request(self, path):
        try:
            response = urlopen(self.base_url + path, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            status = response.status
            content_type = response.headers.get_content_type()
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(content_type, "application/json")
        return status, payload

    def test_health_is_ready(self):
        code, payload = self.request("/api/health")
        self.assertEqual(code, 200)
        self.assertEqual(payload, {"status": "ok", "database": "ok"})

    def test_search_works_with_real_database_even_if_empty(self):
        code, payload = self.request("/api/servidores?page=1&limit=2")
        self.assertEqual(code, 200)
        self.assertIsInstance(payload["items"], list)
        self.assertLessEqual(len(payload["items"]), 2)
        self.assertEqual(payload["pagination"]["page_size"], 2)
        self.assertGreaterEqual(payload["pagination"]["total"], 0)

    def test_alias_and_json_errors(self):
        code, payload = self.request("/api/servants?limit=2")
        self.assertEqual(code, 200)
        self.assertIn("pagination", payload)
        code, payload = self.request("/api/servidores?uf=XX")
        self.assertEqual(code, 400)
        self.assertEqual(payload["error"], "invalid_parameters")
        code, payload = self.request("/api/nonexistent")
        self.assertEqual(code, 404)
        self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()
