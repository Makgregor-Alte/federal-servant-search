"""API security headers, CORS policy and query-size checks."""
import os
import unittest
from unittest.mock import patch

from psycopg import OperationalError
from app import create_app


class SecurityHttpTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()
        self.origin = "http://localhost:5173"

    def test_allowed_origin_receives_cors_headers(self):
        with patch.dict(os.environ, {"ALLOWED_ORIGINS": self.origin}):
            response = self.client.get("/api/missing", headers={"Origin": self.origin})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), self.origin)
        self.assertIn("Origin", response.headers.get("Vary", ""))
        self.assertIsNone(response.headers.get("Access-Control-Allow-Credentials"))

    def test_unlisted_and_unsafe_origins_do_not_receive_cors(self):
        for configured in (self.origin, "*", "null", "https://example.com/path", "http://user:pass@site.test"):
            with self.subTest(configured=configured):
                with patch.dict(os.environ, {"ALLOWED_ORIGINS": configured}):
                    response = self.client.get("/api/missing", headers={"Origin": "https://attacker.example"})
                self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

    def test_untrusted_configured_origin_is_not_allowed(self):
        for value in ("*", "null", "https://example.com/path", "http://user:pass@site.test"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"ALLOWED_ORIGINS": value}):
                    response = self.client.get("/api/health", headers={"Origin": value})
                self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

    def test_valid_preflight(self):
        with patch.dict(os.environ, {"ALLOWED_ORIGINS": self.origin}):
            response = self.client.options("/api/servidores", headers={
                "Origin": self.origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Content-Type",
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), self.origin)
        self.assertIn("GET", response.headers.get("Access-Control-Allow-Methods", ""))
        self.assertIn("Content-Type", response.headers.get("Access-Control-Allow-Headers", ""))
        self.assertEqual(response.headers.get("Access-Control-Max-Age"), "600")

    def test_preflight_does_not_allow_unsafe_method(self):
        with patch.dict(os.environ, {"ALLOWED_ORIGINS": self.origin}):
            response = self.client.options("/api/servidores", headers={
                "Origin": self.origin, "Access-Control-Request-Method": "DELETE",
            })
        self.assertIsNone(response.headers.get("Access-Control-Allow-Methods"))

    def test_preflight_does_not_allow_arbitrary_headers(self):
        with patch.dict(os.environ, {"ALLOWED_ORIGINS": self.origin}):
            response = self.client.options("/api/servidores", headers={
                "Origin": self.origin, "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization, X-Admin",
            })
        self.assertIsNone(response.headers.get("Access-Control-Allow-Headers"))

    def test_security_headers_for_api_only(self):
        with patch.dict(os.environ, {"ALLOWED_ORIGINS": self.origin}):
            api_response = self.client.get("/api/missing", headers={"Origin": self.origin})
            other_response = self.client.get("/other", headers={"Origin": self.origin})
        self.assertEqual(api_response.headers.get("Cache-Control"), "no-store")
        self.assertEqual(api_response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIsNone(other_response.headers.get("Access-Control-Allow-Origin"))

    def test_excessively_large_query_is_413_before_database_access(self):
        with patch("app.routes.connect_db") as connect:
            response = self.client.get("/api/servidores?" + "a" * 5000)
        self.assertEqual(response.status_code, 413)
        self.assertTrue(response.is_json)
        connect.assert_not_called()

    def test_at_limit_request_is_not_rejected_by_size_guard(self):
        with patch("app.routes.connect_db", side_effect=OperationalError("offline")) as connect:
            response = self.client.get("/api/servidores?nome=Ana")
        self.assertEqual(response.status_code, 503)
        connect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
