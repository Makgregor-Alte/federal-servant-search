"""Exact-name API behavior, with an isolated database double."""
import unittest
from unittest.mock import patch

from app import create_app


class ExactHttpTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def test_empty_name_returns_400_without_database_access(self):
        with patch("app.routes.connect_db") as db:
            result = self.client.get("/api/servidores?nome=%20%20%20")
        self.assertEqual(result.status_code, 400)
        self.assertEqual(result.json["error"], "invalid_parameters")
        db.assert_not_called()

    def test_invalid_control_character_returns_400(self):
        with patch("app.routes.connect_db") as db:
            result = self.client.get("/api/servidores?nome=Ana%0ASilva")
        self.assertEqual(result.status_code, 400)
        db.assert_not_called()


if __name__ == "__main__":
    unittest.main()
