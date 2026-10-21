"""Testes das operações de manutenção e das proteções contra perda de dados."""

import importlib.util
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("db_maintenance", ROOT / "scripts" / "db_maintenance.py")
MAINT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MAINT)


class DbMaintenanceTests(unittest.TestCase):
    def test_all_migrations_are_listed_and_in_correct_order(self):
        self.assertEqual(MAINT.MIGRATIONS, (
            "01_schema.sql", "02_model.sql", "03_integrity.sql", "04_indexes.sql"))
        for migration in MAINT.MIGRATIONS:
            self.assertTrue((ROOT / "db" / migration).is_file())

    def test_backup_name_is_outside_project_by_default(self):
        with patch.object(MAINT.uuid, "uuid4") as uuid4:
            uuid4.return_value.hex = "abcdef0123456789"
            path = MAINT._safe_backup_path()
        self.assertEqual(path.parent, ROOT.parent / "federal_servant_backups")
        self.assertTrue(path.name.endswith(".dump"))

    def test_backup_never_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "data.dump"
            target.write_bytes(b"original")
            with self.assertRaises(MAINT.MaintenanceError):
                MAINT._safe_backup_path(output=target)
            self.assertEqual(target.read_bytes(), b"original")

    def test_invalid_backup_is_rejected_before_restoring(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "invalid.dump"
            target.write_bytes(b"not a dump")
            with patch.object(MAINT, "_db") as db:
                with self.assertRaisesRegex(MAINT.MaintenanceError, "formato custom"):
                    MAINT.verify_backup(target)
            db.assert_not_called()

    def test_backup_streams_binary_output_and_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.dump"
            def db_fake(command, *args, stdin=None, stdout=None, timeout=None):
                if "pg_dump" in command:
                    stdout.write(b"PGDMP\x01\x0e\x00data")
                elif "pg_restore --list" in command:
                    self.assertEqual(stdin.read(5), b"PGDMP")
                else:
                    self.fail(command)
                return b""
            with patch.object(MAINT, "_db", side_effect=db_fake):
                result = MAINT.create_backup(output=path)
            self.assertEqual(result, path)
            self.assertEqual(path.read_bytes(), b"PGDMP\x01\x0e\x00data")
            self.assertFalse((Path(folder) / "test.dump.partial").exists())

    def test_failed_backup_does_not_leave_a_partial_or_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.dump"
            with patch.object(MAINT, "_db", side_effect=MAINT.MaintenanceError("error")):
                with self.assertRaises(MAINT.MaintenanceError):
                    MAINT.create_backup(output=path)
            self.assertFalse(path.exists())
            self.assertFalse((Path(folder) / "test.dump.partial").exists())

    def test_migrate_requires_successful_backup_before_any_sql(self):
        history = []
        def fake_db(command, *args, **kwargs):
            history.append(args[0])
            return b""
        with patch.object(MAINT, "create_backup", return_value=Path("backup.dump")) as backup, \
                patch.object(MAINT, "_db", side_effect=fake_db):
            self.assertEqual(MAINT.migrate(), Path("backup.dump"))
            backup.assert_called_once()
        self.assertEqual([Path(x).name for x in history], list(MAINT.MIGRATIONS))
        with patch.object(MAINT, "create_backup", side_effect=MAINT.MaintenanceError("no backup")), \
                patch.object(MAINT, "_db") as db:
            with self.assertRaises(MAINT.MaintenanceError):
                MAINT.migrate()
            db.assert_not_called()

    def test_restore_never_targets_the_existing_database(self):
        for dbname in ("federal_servants", "postgres", "sii_restore_", "sii_restore_X", "sii_restore_x;drop"):
            with self.subTest(dbname=dbname), self.assertRaises(MAINT.MaintenanceError):
                MAINT.restore_backup("none.dump", dbname, confirmed=True)
        with self.assertRaisesRegex(MAINT.MaintenanceError, "--confirm"):
            MAINT.restore_backup("none.dump", "sii_restore_demo")

    def test_restore_creates_separate_database_and_validates_row_count(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "db.dump"
            path.write_bytes(b"PGDMPmock")
            seen = []
            def fake_db(command, *args, **kwargs):
                seen.append((command, args))
                if 'SELECT count(*)' in command:
                    return b"42\n"
                return b""
            with patch.object(MAINT, "verify_backup", return_value={"size_bytes": 9}), \
                    patch.object(MAINT, "_db", side_effect=fake_db):
                self.assertEqual(MAINT.restore_backup(path, "sii_restore_demo", confirmed=True), 42)
            self.assertEqual(len(seen), 3)
            self.assertIn("createdb", seen[0][0])
            self.assertIn("--single-transaction", seen[1][0])
            self.assertEqual(seen[0][1], ("sii_restore_demo",))
            self.assertEqual(seen[1][1], ("sii_restore_demo",))

    def test_restore_does_not_reuse_existing_database_when_createdb_fails(self):
        with patch.object(MAINT, "verify_backup", return_value={}), \
                patch.object(MAINT, "_db", side_effect=MAINT.MaintenanceError("exists")) as db:
            with self.assertRaises(MAINT.MaintenanceError):
                MAINT.restore_backup("db.dump", "sii_restore_demo", confirmed=True)
        self.assertEqual(db.call_count, 1)
        self.assertIn("createdb", db.call_args.args[0])

    def test_persistence_requires_explicit_restart_consent(self):
        with patch.object(MAINT, "_run") as runner:
            with self.assertRaisesRegex(MAINT.MaintenanceError, "--confirm-restart"):
                MAINT.check_persistence()
            runner.assert_not_called()

    def test_compose_command_never_embeds_database_password(self):
        recorded = []
        def fake_run(command, **kwargs):
            recorded.extend(command)
            return subprocess.CompletedProcess(command, 0, stdout=b"ok", stderr=b"")
        with patch.object(MAINT.subprocess, "run", side_effect=fake_run):
            result = MAINT._db('PGPASSWORD="$POSTGRES_PASSWORD" exec pg_isready')
        self.assertEqual(result, b"ok")
        self.assertIn("-T", recorded)
        self.assertNotIn("defina-uma-senha-local", " ".join(recorded))


if __name__ == "__main__":
    unittest.main()
