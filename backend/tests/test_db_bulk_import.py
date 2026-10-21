"""Testa carga incremental e replay seguro sem dependência de servidor externo."""

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

DB = Path(__file__).resolve().parents[2] / "db"
sys.path.insert(0, str(DB))
from import_bulk import INSERT_FROM_STAGE, main, run_bulk
from import_sample import make_sample


class FakeConnection:
    """Simula transações, COPY e unicidade para testar o fluxo do importador."""

    autocommit = True

    def __init__(self):
        self.rows = {}
        self.stage = []
        self.batches = {}
        self.next_id = 1
        self.flushes = 0
        self.max_staged = 0
        self.fail_insert_at = None
        self.insert_attempts = 0

    @contextlib.contextmanager
    def transaction(self):
        snapshot = copy.deepcopy((self.rows, self.stage, self.batches, self.next_id,
                                  self.flushes))
        try:
            yield self
        except BaseException:
            self.rows, self.stage, self.batches, self.next_id, self.flushes = snapshot
            raise

    @contextlib.contextmanager
    def cursor(self):
        yield FakeCursor(self)


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = -1
        self._returned = None

    def execute(self, statement, params=None):
        c = self.connection
        cmd = " ".join(statement.upper().split())
        if cmd.startswith("CREATE TEMP TABLE"):
            return
        if cmd.startswith("INSERT INTO LOTES_IMPORTACAO"):
            batch_id = c.next_id
            c.next_id += 1
            c.batches[batch_id] = {"estado": "iniciado", "lines": 0, "inserted": 0,
                                   "discarded": 0}
            self._returned = (batch_id,)
        elif cmd.startswith("SELECT EXISTS"):
            conflicts = False
            for new in c.stage:
                old = c.rows.get((new[4], new[5]))
                if old is not None and (old[:4], old[6]) != (new[:4], new[6]):
                    conflicts = True
                    break
            self._returned = (conflicts,)
        elif cmd.startswith("TRUNCATE"):
            c.stage.clear()
        elif cmd.startswith("INSERT INTO SERVIDORES"):
            c.insert_attempts += 1
            if c.fail_insert_at == c.insert_attempts:
                raise RuntimeError("simulated database interruption")
            count = 0
            for row in c.stage:
                key = row[4], row[5]
                if key not in c.rows:
                    c.rows[key] = row
                    count += 1
            self.rowcount = count
            c.flushes += 1
        elif cmd.startswith("UPDATE LOTES_IMPORTACAO"):
            if "COALESCE" in cmd:
                month, read, ins, discard, state, _, batch_id = params
                if state is not None:
                    c.batches[batch_id]["estado"] = state
            else:
                month, read, ins, discard, batch_id = params
            c.batches[batch_id].update({"competencia": month, "lines": read,
                                        "inserted": ins, "discarded": discard})
        else:
            raise AssertionError("SQL não previsto: " + cmd[:80])

    def fetchone(self):
        return self._returned

    @contextlib.contextmanager
    def copy(self, statement):
        self.connection.stage.clear()
        yield FakeCopy(self.connection)


class FakeCopy:
    def __init__(self, connection):
        self.connection = connection

    def write_row(self, row):
        self.connection.stage.append(row)
        self.connection.max_staged = max(self.connection.max_staged,
                                          len(self.connection.stage))


class TypedParameterCursor(FakeCursor):
    def execute(self, statement, params=None):
        import re
        if re.search(r"%s\s+IS\s+NOT\s+NULL", statement, flags=re.IGNORECASE):
            raise RuntimeError("could not determine data type of parameter")
        super().execute(statement, params)


class TypedParameterConnection(FakeConnection):
    @contextlib.contextmanager
    def cursor(self):
        yield TypedParameterCursor(self)


class BulkImportTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.path = Path(t.name) / "aposentados.csv"
        self.carreiras = Path(t.name) / "carreiras.txt"

    def write_aposentados(self, rows=5, broken=False):
        with self.path.open("w", encoding="utf-8", newline="") as handle:
            handle.write("Nome;Cargo;Nome do órgão;CPF\n")
            for i in range(rows):
                handle.write(f"Pessoa {i:05d};Analista;Universidade;segredo-{i}\n")
            if broken:
                handle.write(";Cargo;Universidade;cpf\n")

    def test_dry_run_never_opens_db_and_omits_pii(self):
        self.write_aposentados(3, broken=True)
        summary = run_bulk(self.path, "aposentados", batch_size=2)
        self.assertEqual((summary["linhas_lidas"], summary["aceitas"],
                          summary["rejeitadas"]), (4, 3, 1))
        self.assertEqual(summary["modo"], "validacao")
        self.assertNotIn("importadas", summary)
        self.assertNotIn("segredo", json.dumps(summary))
        self.assertNotIn("Pessoa", json.dumps(summary))
        self.assertEqual(summary["ocorrencias"], {"nome_ausente": 1})

    def test_copy_batch_size_and_counts(self):
        self.write_aposentados(7, broken=True)
        conn = FakeConnection()
        r = run_bulk(self.path, "aposentados", batch_size=3, connection=conn,
                     competence="2026-05")
        self.assertEqual((r["importadas"], r["ja_existentes"], r["rejeitadas"]),
                         (7, 0, 1))
        self.assertEqual((r["lotes_gravados"], conn.max_staged), (3, 3))
        self.assertEqual(len(conn.rows), 7)
        self.assertTrue(all(row[3] is None for row in conn.rows.values()))
        self.assertTrue(all(row[-1] == "2026-05-01" for row in conn.rows.values()))
        self.assertEqual(conn.batches[1]["estado"], "concluido")
        self.assertEqual(conn.batches[1]["discarded"], 1)

    def test_bulk_finalizes_with_explicitly_typed_optional_parameters(self):
        # Models PostgreSQL rejecting an untyped placeholder before IS NOT NULL.
        self.write_aposentados(7, broken=True)
        connection = TypedParameterConnection()
        report = run_bulk(self.path, "aposentados", batch_size=3,
                          competence="2026-05", connection=connection)
        self.assertEqual(report["importadas"], 7)
        self.assertEqual(connection.batches[1]["estado"], "concluido")
        self.assertEqual(connection.batches[1]["inserted"], 7)
        self.assertEqual(connection.batches[1]["discarded"], 1)

    def test_failed_batch_finalizes_with_typed_state(self):
        self.write_aposentados(5)
        connection = TypedParameterConnection()
        connection.fail_insert_at = 2
        with self.assertRaisesRegex(RuntimeError, "simulated database interruption"):
            run_bulk(self.path, "aposentados", batch_size=2, connection=connection)
        self.assertEqual(connection.batches[1]["estado"], "falhou")
        self.assertEqual(connection.batches[1]["inserted"], 2)

    def test_replay_is_idempotent_and_compatible_with_sample(self):
        self.write_aposentados(110)
        conn = FakeConnection()
        a = run_bulk(self.path, "aposentados", batch_size=30, max_rows=100, connection=conn)
        b = run_bulk(self.path, "aposentados", batch_size=30, connection=conn)
        c = run_bulk(self.path, "aposentados", batch_size=30, connection=conn)
        self.assertEqual([a["importadas"], b["importadas"], c["importadas"]],
                         [100, 10, 0])
        self.assertEqual([a["ja_existentes"], b["ja_existentes"], c["ja_existentes"]],
                         [0, 100, 110])
        sample = make_sample(self.path, "aposentados", max_rows=100)
        self.assertEqual({row[5] for row in sample.rows}, {row[5] for row in conn.rows.values()
                                                         if row[0] in {r[0] for r in sample.rows}})
        self.assertEqual(len(conn.rows), 110)

    def test_partial_failure_keeps_previous_batches_and_replay_finishes(self):
        self.write_aposentados(5)
        conn = FakeConnection()
        conn.fail_insert_at = 2
        with self.assertRaises(RuntimeError):
            run_bulk(self.path, "aposentados", batch_size=2, connection=conn)
        self.assertEqual(len(conn.rows), 2)
        self.assertEqual(conn.batches[1]["estado"], "falhou")
        self.assertEqual(conn.batches[1]["inserted"], 2)
        conn.fail_insert_at = None
        r = run_bulk(self.path, "aposentados", batch_size=2, connection=conn)
        self.assertEqual((r["importadas"], r["ja_existentes"]), (3, 2))
        self.assertEqual(len(conn.rows), 5)
        self.assertEqual(conn.batches[2]["estado"], "concluido")

    def test_batch_of_rejected_lines_can_complete(self):
        self.path.write_text("Nome;Cargo;Nome do órgão\n;A;B\n", encoding="utf-8")
        conn = FakeConnection()
        result = run_bulk(self.path, "aposentados", connection=conn)
        self.assertEqual((result["aceitas"], result["rejeitadas"], result["importadas"]),
                         (0, 1, 0))
        self.assertEqual(result["lotes_gravados"], 0)
        self.assertEqual(conn.batches[1]["estado"], "concluido")

    def test_all_rows_bounded_in_memory(self):
        self.write_aposentados(12005)
        conn = FakeConnection()
        result = run_bulk(self.path, "aposentados", batch_size=250, connection=conn)
        self.assertEqual(result["lotes_gravados"], 49)
        self.assertEqual(result["importadas"], 12005)
        self.assertLessEqual(conn.max_staged, 250)

    def test_carreiras_competence_detected_with_uf(self):
        self.carreiras.write_text(
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência\n"
            "José;Professor;rs;Universidade;05/2026\n", encoding="utf-8")
        conn = FakeConnection()
        result = run_bulk(self.carreiras, "carreiras", connection=conn)
        self.assertEqual(result["competencia"], "2026-05-01")
        self.assertEqual(next(iter(conn.rows.values()))[3], "RS")
        self.assertEqual(conn.batches[1]["competencia"], "2026-05-01")

    def test_mixed_competences_fail_before_writing(self):
        self.carreiras.write_text(
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência\n"
            "José;Professor;RS;Universidade;05/2026\n"
            "Maria;Professora;RS;Universidade;06/2026\n", encoding="utf-8")
        conn = FakeConnection()
        with self.assertRaisesRegex(ValueError, "Mais de uma competencia"):
            run_bulk(self.carreiras, "carreiras", batch_size=1, connection=conn)
        self.assertEqual(conn.batches, {})
        self.assertEqual(len(conn.rows), 0)

    def test_explicit_competence_mismatch_fails_without_creating_results(self):
        self.carreiras.write_text(
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência\n"
            "José;Professor;RS;Universidade;05/2026\n", encoding="utf-8")
        conn = FakeConnection()
        with self.assertRaisesRegex(ValueError, "diverge"):
            run_bulk(self.carreiras, "carreiras", competence="2026-04", connection=conn)
        self.assertFalse(conn.batches)
        self.assertFalse(conn.rows)

    def test_inferred_competence_applies_to_earlier_rows(self):
        self.carreiras.write_text(
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência\n"
            "Ana;Docente;RS;Universidade;\n"
            "Bia;Docente;RS;Universidade;05/2026\n"
            "Caio;Docente;RS;Universidade;\n", encoding="utf-8")
        conn = FakeConnection()
        result = run_bulk(self.carreiras, "carreiras", batch_size=1, connection=conn)
        self.assertEqual(result["competencia"], "2026-05-01")
        self.assertEqual(len(conn.rows), 3)
        self.assertTrue(all(row[6] == "2026-05-01" for row in conn.rows.values()))
        self.assertEqual(conn.batches[1]["competencia"], "2026-05-01")

    def test_invalid_month_in_later_batch_prevents_earlier_writes(self):
        self.carreiras.write_text(
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência\n"
            "Ana;Docente;RS;Universidade;05/2026\n"
            "Bia;Docente;RS;Universidade;17/2026\n", encoding="utf-8")
        conn = FakeConnection()
        with self.assertRaisesRegex(ValueError, "Competencia invalida"):
            run_bulk(self.carreiras, "carreiras", batch_size=1, connection=conn)
        self.assertEqual(conn.batches, {})
        self.assertEqual(conn.rows, {})
        with self.assertRaisesRegex(ValueError, "Competencia invalida"):
            run_bulk(self.carreiras, "carreiras")

    def test_validated_prefix_does_not_infer_month_from_later_rows(self):
        self.carreiras.write_text(
            "Nome;Descrição do Cargo/Emprego;UF da UPAG de vinculação;"
            "Denominação do Órgão de atuação;Mês de referência\n"
            "Ana;Docente;RS;Universidade;\n"
            "Bia;Docente;RS;Universidade;05/2026\n", encoding="utf-8")
        conn = FakeConnection()
        result = run_bulk(self.carreiras, "carreiras", max_rows=1, connection=conn)
        self.assertIsNone(result["competencia"])
        self.assertEqual(len(conn.rows), 1)
        self.assertIsNone(next(iter(conn.rows.values()))[6])

    def test_invalid_arguments_rejected_before_db_writes(self):
        self.write_aposentados(1)
        for params in ({"batch_size": 0}, {"batch_size": 10001},
                       {"max_rows": 0}, {"competence": "2026-17"}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                run_bulk(self.path, "aposentados", **params, connection=FakeConnection())
        conn = FakeConnection()
        conn.autocommit = False
        with self.assertRaisesRegex(ValueError, "autocommit"):
            run_bulk(self.path, "aposentados", connection=conn)

    def test_cli_dry_run_is_safe_and_apply_requires_db(self):
        self.write_aposentados(2)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--file", str(self.path), "--source", "aposentados"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["aceitas"], 2)
        self.assertNotIn("Pessoa", out.getvalue())
        out, err = io.StringIO(), io.StringIO()
        with patch.dict("os.environ", {"DATABASE_URL": "", "PGHOST": ""}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--file", str(self.path), "--source", "aposentados", "--apply"])
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("ValueError", err.getvalue())
        self.assertNotIn("Pessoa", err.getvalue())

    def test_sql_uses_copy_and_conflict(self):
        self.assertIn("ON CONFLICT (fonte, id_origem) DO NOTHING", INSERT_FROM_STAGE)
        self.assertIn("WHERE TRUE", INSERT_FROM_STAGE)


if __name__ == "__main__":
    unittest.main()
