"""API responses and database connection limits under overload."""
import logging
import os
import unittest
from unittest.mock import patch

import psycopg

from app import create_app
from app.routes import DB_TIMEOUT_OPTIONS, FUZZY_DB_TIMEOUT_OPTIONS, connect_db


class RuntimeLimitTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()

    def test_database_connection_sets_bounded_statement_lock_and_connect_timeouts(self):
        self.assertIn("statement_timeout=3000", DB_TIMEOUT_OPTIONS)
        self.assertIn("lock_timeout=1000", DB_TIMEOUT_OPTIONS)
        with self.app.app_context():
            self.app.config["DATABASE_URL"] = "postgresql://localhost/placeholder"
            with patch("app.routes.psycopg.connect") as connect:
                connect_db()
            connect.assert_called_once()
            self.assertEqual(connect.call_args.args[0], self.app.config["DATABASE_URL"])
            self.assertEqual(connect.call_args.kwargs["connect_timeout"], 5)
            self.assertEqual(connect.call_args.kwargs["options"], DB_TIMEOUT_OPTIONS)

            self.app.config["DATABASE_URL"] = ""
            with patch.dict(os.environ, {"PGHOST": "localhost"}):
                with patch("app.routes.psycopg.connect") as connect:
                    connect_db()
            connect.assert_called_once()
            self.assertNotIn("args", connect.call_args.kwargs)
            self.assertEqual(connect.call_args.kwargs["options"], DB_TIMEOUT_OPTIONS)
            self.assertEqual(connect.call_args.kwargs["connect_timeout"], 5)

    def test_fuzzy_search_uses_longer_bounded_database_timeout(self):
        self.assertIn("statement_timeout=6000", FUZZY_DB_TIMEOUT_OPTIONS)
        self.assertIn("lock_timeout=1000", FUZZY_DB_TIMEOUT_OPTIONS)
        with self.app.app_context():
            self.app.config["DATABASE_URL"] = "postgresql://localhost/placeholder"
            with patch("app.routes.psycopg.connect") as connect:
                connect_db(fuzzy=True)
            self.assertEqual(connect.call_args.kwargs["options"], FUZZY_DB_TIMEOUT_OPTIONS)

    def test_statement_timeout_is_504_and_has_no_secret_in_logs_or_json(self):
        secret = "private-connection-string-do-not-log"
        with patch("app.routes.connect_db", side_effect=psycopg.errors.QueryCanceled(secret)):
            with self.assertLogs(self.app.logger.name, level=logging.WARNING) as records:
                result = self.client.get("/api/servidores?nome=Ana")
        self.assertEqual(result.status_code, 504)
        self.assertEqual(result.json["error"], "timeout")
        self.assertNotIn(secret, result.get_data(as_text=True))
        self.assertNotIn(secret, "\n".join(records.output))

    def test_lock_timeout_is_504(self):
        with patch("app.routes.connect_db", side_effect=psycopg.errors.LockNotAvailable("lock-detail")):
            result = self.client.get("/api/servants")
        self.assertEqual(result.status_code, 504)
        self.assertEqual(result.json["error"], "timeout")
        self.assertNotIn("lock-detail", result.get_data(as_text=True))

    def test_connection_failure_remains_503(self):
        with patch("app.routes.connect_db", side_effect=psycopg.OperationalError("db-down")):
            result = self.client.get("/api/servidores")
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json["error"], "database_unavailable")

    def test_invalid_parameters_still_rejected_before_db(self):
        with patch("app.routes.connect_db") as connect:
            result = self.client.get("/api/servidores?uf=INVALID")
        self.assertEqual(result.status_code, 400)
        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
