"""Consultas e perfis de índices: query-plan diagnostics without reliance on production data."""
import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("profile_indexes", ROOT / "db" / "profile_indexes.py")
PROFILER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILER)


class QueryPlanProfilerTests(unittest.TestCase):
    def test_collect_nested_indexes_and_buffer_metrics(self):
        summary = PROFILER.plan_summary({
            "Planning Time": 0.45678, "Execution Time": 3.45123,
            "Plan": {
                "Node Type": "Sort", "Actual Rows": 7,
                "Shared Hit Blocks": 22, "Shared Read Blocks": 3,
                "Plans": [{"Node Type": "Bitmap Heap Scan", "Index Name": "idx_cargo",
                           "Plans": [{"Node Type": "Bitmap Index Scan",
                                      "Index Name": "idx_nome"}]}],
            },
        })
        self.assertEqual(summary["indexes"], ["idx_cargo", "idx_nome"])
        self.assertEqual(summary["buffers"]["shared_hit_blocks"], 22)
        self.assertEqual(summary["buffers"]["shared_read_blocks"], 3)
        self.assertEqual(summary["execution_ms"], 3.451)
        self.assertEqual(summary["plan_nodes"], ["Bitmap Heap Scan", "Bitmap Index Scan", "Sort"])

    def test_aggregate_uses_median_and_nearest_rank_p95(self):
        def case(n):
            return {"execution_ms": float(n), "planning_ms": 0.2,
                    "indexes": ["idx_nome"], "plan_nodes": ["Index Scan"],
                    "returned_rows": 20, "buffers": {"shared_read_blocks": n}}
        result = PROFILER.summarize_runs([case(n) for n in (9, 2, 4, 3, 7)])
        self.assertEqual(result["median_ms"], 4.0)
        self.assertEqual(result["p95_ms"], 9.0)
        self.assertEqual(result["samples"], 5)
        self.assertEqual(result["buffers_last_run"], {"shared_read_blocks": 7})

    def test_combined_case_and_name_mode(self):
        args = SimpleNamespace(name=None, similar="ANA", pattern=None,
                               cargo="Docente", orgao=None, uf="RS", combined=True)
        cases = PROFILER.search_cases(args)
        self.assertEqual(cases[-1], ("combinada", {"similar": "ANA", "cargo": "Docente", "uf": "RS"}))
        args.pattern = "%ANA%"
        with self.assertRaisesRegex(ValueError, "unico modo"):
            PROFILER.search_cases(args)

    def test_profile_query_executes_warmups_and_excludes_them(self):
        class Cursor:
            def __init__(self):
                self.calls = []
                self.position = 0
            def execute(self, sql, params):
                self.calls.append((sql, params))
            def fetchone(self):
                self.position += 1
                return ([{"Planning Time": 0.1, "Execution Time": float(self.position),
                          "Plan": {"Actual Rows": 2}}],)
        cursor = Cursor()
        result = PROFILER.profile_query(cursor, "SELECT 1", {}, repeats=3, warmups=1)
        self.assertEqual(len(cursor.calls), 4)
        self.assertTrue(all("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)" in sql
                            for sql, _ in cursor.calls))
        self.assertEqual(result["median_ms"], 3.0)
        self.assertEqual(result["samples"], 3)

    def test_cases_preserve_parameterized_queries(self):
        class Cursor:
            def __init__(self):
                self.calls = []
            def execute(self, sql, params):
                self.calls.append((sql, params))
            def fetchone(self):
                return (json.dumps([{"Planning Time": .1, "Execution Time": .2,
                                     "Plan": {"Actual Rows": 0}}]),)
        cursor = Cursor()
        PROFILER.profile_case(cursor, {"cargo": "X' OR 1=1 --", "uf": "RS"},
                              repeats=1, warmups=0, page=2, limit=10)
        self.assertEqual(len(cursor.calls), 2)
        for sql, params in cursor.calls:
            self.assertNotIn("X' OR 1=1 --", sql)
            self.assertTrue(sql.startswith("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT"))
        self.assertEqual(cursor.calls[0][1]["position"], "%X' OR 1=1 --%")
        self.assertEqual(cursor.calls[1][1]["offset"], 10)

    def test_cli_rejects_excessive_repetitions_without_database(self):
        with self.assertRaises(SystemExit) as stopped:
            PROFILER.main(["--uf", "RS", "--repeat", "11"])
        self.assertEqual(stopped.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
