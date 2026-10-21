"""Integration tests exercising Flask routes against an isolated PostgreSQL fixture."""
import os
import unittest
from unittest.mock import patch


@unittest.skipUnless(
    os.getenv("RUN_DB_INTEGRATION_TESTS") == "1",
    "requires a PostgreSQL test environment",
)
class PostgreSQLApiIntegrationTests(unittest.TestCase):
    ROWS = (
        (1, "Maria Silva", "Analista de Sistemas", "Universidade Federal do Rio Grande", "RS", "carreiras"),
        (2, "MARIA SILVA", "Tecnica de Laboratorio", "Universidade Federal do Rio Grande", "RS", "carreiras"),
        (3, "Marina Silva", "Analista", "Instituto Federal Sul-Rio-Grandense", "RS", "carreiras"),
        (4, "Maria Silva", "Analista", "Universidade Federal do Rio Grande", "SP", "carreiras"),
        (5, "Joao Silva", "Aposentado", "Universidade Federal do Rio Grande", None, "aposentados"),
        (6, "Ana Maria Silva", "Analista", "Universidade Federal do Rio Grande", "RS", "carreiras"),
        (7, "Pedro Santos", "Professor", "Universidade Federal de Pelotas", "RS", "carreiras"),
    )

    @classmethod
    def setUpClass(cls):
        import psycopg
        from app import create_app

        cls.psycopg = psycopg
        cls.app = create_app()
        cls.app.testing = True
        cls.client = cls.app.test_client()
        # The search SQL depends on this extension; initialization is the DB layer's job.
        with cls._new_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
                if cursor.fetchone() is None:
                    raise AssertionError("pg_trgm missing: initialize db/01_schema.sql first")

    @classmethod
    def _new_connection(cls):
        from psycopg.rows import dict_row

        return cls.psycopg.connect(
            os.getenv("DATABASE_URL") or "",
            row_factory=dict_row,
            connect_timeout=5,
        )

    def _fixture_connection(self, **_options):
        connection = self._new_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """CREATE TEMP TABLE servidores (
                        id BIGINT PRIMARY KEY,
                        nome TEXT NOT NULL,
                        cargo TEXT NOT NULL,
                        orgao TEXT NOT NULL,
                        uf CHAR(2),
                        fonte TEXT NOT NULL
                    ) ON COMMIT PRESERVE ROWS"""
                )
                cursor.executemany(
                    "INSERT INTO servidores (id, nome, cargo, orgao, uf, fonte) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    self.ROWS,
                )
            connection.commit()
            return connection
        except Exception:
            connection.close()
            raise

    def request(self, path):
        # Each request gets its own temporary table: real SQL, no permanent writes.
        with patch("app.routes.connect_db", side_effect=self._fixture_connection):
            return self.client.get(path)

    def test_health_uses_real_database_connection(self):
        response = self.request("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok", "database": "ok"})

    def test_exact_name_returns_real_rows_and_metadata(self):
        response = self.request("/api/servidores?nome=maria%20silva&limit=10")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r["id"] for r in response.json["items"]], [1, 2, 4])
        self.assertEqual(response.json["pagination"], {
            "page": 1, "page_size": 10, "total": 3, "pages": 1,
        })
        self.assertEqual(
            set(response.json["items"][0]),
            {"id", "nome", "cargo", "orgao", "uf", "fonte"},
        )

    def test_individual_position_agency_and_uf_filters(self):
        expected = (
            ("cargo=Professor", [7]),
            ("orgao=Pelotas", [7]),
            ("uf=SP", [4]),
            ("uf=RS", [1, 2, 3, 6, 7]),
        )
        for query, ids in expected:
            with self.subTest(query=query):
                response = self.request("/api/servidores?" + query)
                self.assertEqual(response.status_code, 200)
                self.assertEqual({r["id"] for r in response.json["items"]}, set(ids))
        # In particular, the aposentado with no UF must not be given a fabricated state.
        response = self.request("/api/servidores?uf=RS")
        self.assertNotIn(5, {r["id"] for r in response.json["items"]})

    def test_multiple_filters_return_the_intersection(self):
        response = self.request(
            "/api/servidores?nome=Maria%20Silva&cargo=Analista&orgao=Universidade&uf=rs"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r["id"] for r in response.json["items"]], [1])

    def test_pattern_search_with_all_required_wildcard_forms(self):
        cases = (
            ("%25MARIA%25SILVA%25", {1, 2, 4, 6}),
            ("MARIA%20SILVA%25", {1, 2, 4}),
            ("MARIA%25SILVA", {1, 2, 4}),
        )
        for pattern, matching_ids in cases:
            with self.subTest(pattern=pattern):
                response = self.request("/api/servidores?similar=" + pattern + "&limit=100")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    {r["id"] for r in response.json["items"]}, matching_ids
                )

    def test_similarity_query_uses_pg_trgm(self):
        response = self.request("/api/servidores?similar=Maria%20Silva&limit=100")
        self.assertEqual(response.status_code, 200)
        self.assertTrue({1, 2, 4}.issubset({r["id"] for r in response.json["items"]}))

    def test_pagination_is_deterministic_and_out_of_range_is_json_404(self):
        pages = []
        for number in range(1, 5):
            response = self.request(f"/api/servidores?pagina={number}&limit=2")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["pagination"], {
                "page": number, "page_size": 2, "total": 7, "pages": 4,
            })
            pages.extend(r["id"] for r in response.json["items"])
        self.assertEqual(pages, [6, 5, 1, 2, 4, 3, 7])

        response = self.request("/api/servidores?pagina=5&limit=2")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json["error"], "page_not_found")
        self.assertEqual(response.json["items"], [])

    def test_empty_result_is_200_on_first_page_and_404_after_that(self):
        empty = self.request("/api/servidores?nome=Nome%20Inexistente")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json["items"], [])
        self.assertEqual(empty.json["pagination"]["total"], 0)
        missing = self.request("/api/servidores?nome=Nome%20Inexistente&pagina=2")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json["error"], "page_not_found")

    def test_sql_injection_input_is_treated_as_data(self):
        response = self.request(
            "/api/servidores?nome=%27%20OR%201%3D1%20--&limit=100"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["items"], [])
        self.assertEqual(response.json["pagination"]["total"], 0)

    def test_invalid_inputs_are_rejected_before_connecting(self):
        with patch("app.routes.connect_db") as connect:
            for query in (
                "uf=XX", "cargo=", "nome=", "limit=101", "pagina=0",
                "nome=Ana&nome=Maria", "orgao=FURG&agency=FURG",
                "nome=%27%3B%20DROP%20TABLE%20servidores%3B--&uf=XX",
            ):
                with self.subTest(query=query):
                    result = self.client.get("/api/servidores?" + query)
                    self.assertEqual(result.status_code, 400)
                    self.assertEqual(result.json["error"], "invalid_parameters")
            connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
