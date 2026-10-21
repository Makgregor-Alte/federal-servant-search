"""HTTP error responses and safe logging for the API."""
import logging
import unittest
from unittest.mock import patch

import psycopg
from flask import abort

from app import create_app


class ApiErrorTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()

    def test_unknown_api_route_returns_generic_json_404(self):
        for path in ("/api", "/api/unknown"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertTrue(response.is_json)
                self.assertEqual(response.json, {
                    "error": "http_error", "message": "Recurso nao encontrado",
                })

    def test_method_not_allowed_is_json_and_keeps_allow_header(self):
        response = self.client.post("/api/servidores")
        self.assertEqual(response.status_code, 405)
        self.assertTrue(response.is_json)
        self.assertEqual(response.json["error"], "http_error")
        self.assertIn("GET", response.headers["Allow"])

    def test_non_api_404_keeps_default_flask_response(self):
        response = self.client.get("/not-an-api")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.is_json)

    def test_invalid_parameters_are_400_and_do_not_query(self):
        with patch("app.routes.connect_db") as connect:
            response = self.client.get("/api/servidores?uf=INVALID")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["error"], "invalid_parameters")
        connect.assert_not_called()

    def test_database_error_is_503_without_sensitive_data_in_body_or_log(self):
        secret = "postgres-password-example-sensitive"
        with patch("app.routes.connect_db", side_effect=psycopg.OperationalError(secret)):
            with self.assertLogs(self.app.logger.name, level=logging.ERROR) as logs:
                response = self.client.get("/api/servidores")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json, {
            "error": "database_unavailable", "message": "Falha ao consultar o banco de dados",
        })
        self.assertNotIn(secret, response.get_data(as_text=True))
        self.assertNotIn(secret, "\n".join(logs.output))

    def test_health_check_database_error_does_not_log_credentials(self):
        secret = "postgres-password-example-sensitive"
        with patch("app.routes.connect_db", side_effect=psycopg.OperationalError(secret)):
            with self.assertLogs(self.app.logger.name, level=logging.WARNING) as logs:
                response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json, {"status": "degraded", "database": "unavailable"})
        self.assertNotIn(secret, "\n".join(logs.output))

    def test_unexpected_exception_is_500_json_and_not_leaked(self):
        secret = "internal-sensitive-detail"
        with patch("app.routes.connect_db", side_effect=RuntimeError(secret)):
            with self.assertLogs(self.app.logger.name, level=logging.ERROR) as logs:
                response = self.client.get("/api/servidores")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json, {
            "error": "internal_error", "message": "Erro interno do servidor",
        })
        self.assertNotIn(secret, response.get_data(as_text=True))
        self.assertNotIn(secret, "\n".join(logs.output))

    def test_registered_http_errors_are_json_without_internal_details(self):
        @self.app.get("/api/__test_errors")
        def injected_http_errors():
            abort(429, description="sensitive-rate-details")

        response = self.client.get("/api/__test_errors")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json["error"], "rate_limited")
        self.assertNotIn("sensitive-rate-details", response.get_data(as_text=True))

    def test_http_gateway_timeout_is_json(self):
        @self.app.get("/api/__test_timeout")
        def injected_timeout():
            abort(504, description="database-dsn")

        response = self.client.get("/api/__test_timeout")
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json["error"], "timeout")
        self.assertNotIn("database-dsn", response.get_data(as_text=True))

    def test_missing_database_configuration_maps_to_503(self):
        with patch.dict("os.environ", {"PGHOST": ""}):
            with patch.dict(self.app.config, {"DATABASE_URL": ""}):
                with self.assertLogs(self.app.logger.name, level=logging.ERROR):
                    response = self.client.get("/api/servidores")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["error"], "database_unavailable")


if __name__ == "__main__":
    unittest.main()
