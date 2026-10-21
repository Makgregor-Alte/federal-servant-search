"""Teste opcional de recuperação real, executado somente quando autorizado."""

import importlib.util
import os
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("db_maintenance_real", ROOT / "scripts" / "db_maintenance.py")
MAINT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MAINT)


@unittest.skipUnless(os.environ.get("RUN_DB_MAINTENANCE_TESTS") == "1",
                     "requires explicit permission and running Docker Compose")
class PostgreSQLRecoveryTests(unittest.TestCase):
    def test_backup_restores_into_a_separate_database(self):
        original_count = MAINT._row_count()
        target_name = "sii_restore_test_" + uuid.uuid4().hex[:12]
        created = False
        with tempfile.TemporaryDirectory() as folder:
            backup = MAINT.create_backup(directory=folder)
            self.assertTrue(backup.is_file())
            with backup.open("rb") as stream:
                self.assertEqual(stream.read(5), b"PGDMP")
            try:
                restored_count = MAINT.restore_backup(backup, target_name, confirmed=True)
                created = True
                self.assertEqual(restored_count, original_count)
                self.assertEqual(MAINT._row_count(), original_count)
            finally:
                if created:
                    MAINT._db(
                        'PGPASSWORD="$POSTGRES_PASSWORD" exec dropdb '
                        '-U "$POSTGRES_USER" -- "$1"',
                        target_name,
                    )


if __name__ == "__main__":
    unittest.main()
