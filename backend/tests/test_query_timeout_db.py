"""Optional real-PostgreSQL verification of server-enforced query timeouts."""
import os
import unittest


@unittest.skipUnless(os.environ.get("RUN_DB_INTEGRATION_TESTS") == "1", "requires PostgreSQL test environment")
class QueryTimeoutDatabaseTests(unittest.TestCase):
    def test_long_running_sql_is_cancelled_by_postgresql(self):
        import psycopg
        from psycopg.errors import QueryCanceled

        with psycopg.connect(os.environ.get("DATABASE_URL", ""), options="-c statement_timeout=100") as conn:
            with conn.cursor() as cursor:
                with self.assertRaises(QueryCanceled):
                    cursor.execute("SELECT pg_sleep(0.4)")


if __name__ == "__main__":
    unittest.main()
