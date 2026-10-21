"""Verifica o contrato de prontidão entre Flask e PostgreSQL."""

import importlib.util
import re
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
DEPENDENCIES_PRESENT = (
    importlib.util.find_spec("flask") is not None
    and importlib.util.find_spec("psycopg") is not None
)


class ReadinessSchemaTests(unittest.TestCase):
    def test_readiness_fields_exist_in_schema_and_search_projection(self):
        schema = (ROOT / "db/01_schema.sql").read_text("utf-8")
        routes = (ROOT / "backend/app/routes.py").read_text("utf-8")
        search = (ROOT / "backend/app/search.py").read_text("utf-8")
        required = ("id", "nome", "cargo", "orgao", "uf", "fonte")
        for field in required:
            with self.subTest(field=field):
                self.assertRegex(schema, rf"(?mi)^\s*{field}\s+")
                self.assertIn(field, routes)
                self.assertIn(field, search)
        self.assertIn("SELECT similarity(", routes)
        self.assertIn("LIMIT 0", routes)
        self.assertNotIn("SELECT * FROM servidores", routes)

    def test_bulk_copy_columns_match_insert_and_database_model(self):
        from db.import_bulk import COPY_STAGE, CREATE_STAGE, INSERT_FROM_STAGE

        initial = (ROOT / "db/01_schema.sql").read_text("utf-8")
        model = (ROOT / "db/02_model.sql").read_text("utf-8")
        copy_match = re.search(
            r"COPY pg_temp\.importacao_servidores_stage\s*\(([^)]+)\)", COPY_STAGE
        )
        insert_match = re.search(r"INSERT INTO servidores\s*\(([^)]+)\)", INSERT_FROM_STAGE)
        self.assertIsNotNone(copy_match)
        self.assertIsNotNone(insert_match)
        copy_fields = tuple(field.strip() for field in copy_match.group(1).split(","))
        insert_fields = tuple(field.strip() for field in insert_match.group(1).split(","))
        self.assertEqual(insert_fields, copy_fields + ("lote_importacao_id",))
        for field in insert_fields:
            with self.subTest(field=field):
                schema = initial if field in {"id", "nome", "cargo", "orgao", "uf", "fonte", "id_origem"} else model
                self.assertRegex(schema, rf"(?mi)\b{field}\s+(?:TEXT|CHAR|DATE|BIGINT)\b")
        self.assertIn("ON CONFLICT (fonte, id_origem) DO NOTHING", INSERT_FROM_STAGE)
        self.assertIn("ON COMMIT PRESERVE ROWS", CREATE_STAGE)

    def test_readiness_query_does_not_depend_on_imported_records(self):
        routes = (ROOT / "backend/app/routes.py").read_text("utf-8")
        self.assertIn("FROM servidores LIMIT 0", routes)
        self.assertIn("except (psycopg.Error, OSError, RuntimeError)", routes)



class FakeConnection:
    def __init__(self, *, fail_on=None, exception=None):
        self.statements = []
        self.fail_on = fail_on
        self.exception = exception

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self

    def execute(self, query, params=None):
        self.statements.append(query)
        if self.fail_on and self.fail_on in query:
            raise self.exception


@unittest.skipUnless(DEPENDENCIES_PRESENT, "requires Flask and Psycopg")
class ReadinessHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from app import create_app
        cls.psycopg = psycopg
        cls.app = create_app()
        cls.app.testing = True
        cls.client = cls.app.test_client()

    def test_healthy_requires_table_columns_and_trigram_function(self):
        conn = FakeConnection()
        with patch("app.routes.connect_db", return_value=conn):
            response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok", "database": "ok"})
        self.assertEqual(len(conn.statements), 3)
        self.assertIn("FROM servidores LIMIT 0", conn.statements[1])
        self.assertIn("similarity", conn.statements[2])

    def test_missing_table_returns_503_without_sql_details(self):
        conn = FakeConnection(fail_on="FROM servidores", exception=self.psycopg.errors.UndefinedTable("private table details"))
        with patch("app.routes.connect_db", return_value=conn):
            response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json, {"status": "degraded", "database": "unavailable"})
        self.assertNotIn("private", response.get_data(as_text=True))

    def test_missing_trigram_returns_503_without_internal_details(self):
        conn = FakeConnection(fail_on="similarity", exception=self.psycopg.errors.UndefinedFunction("secret internal details"))
        with patch("app.routes.connect_db", return_value=conn):
            response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["status"], "degraded")
        self.assertNotIn("secret", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
