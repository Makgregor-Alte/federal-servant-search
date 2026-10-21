"""Verificacao de aceite do banco e do contrato HTTP, sem dados pessoais nos relatórios."""

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from db.acceptance import (REQUIRED_COLUMNS, REQUIRED_CONSTRAINTS,
                           REQUIRED_INDEXES, collect_snapshot, evaluate_snapshot)
from scripts.validate_database import check_http, checksum


def valid_snapshot():
    return {
        "columns": {key: set(value) for key, value in REQUIRED_COLUMNS.items()},
        "indexes": set(REQUIRED_INDEXES),
        "constraints": {key: True for key in REQUIRED_CONSTRAINTS},
        "pg_trgm": True,
        "sources": {
            "aposentados": {"registros": 2, "sem_uf": 2, "sem_lote": 0},
            "carreiras": {"registros": 3, "sem_uf": 0, "sem_lote": 0},
        },
        "data_issues": {"nome_vazio": 0, "id_origem_vazio": 0, "uf_invalida": 0},
        "batches": {"aposentados": {"concluido": 1}, "carreiras": {"concluido": 1}},
        "provenance": {"aposentados": {"a" * 64}, "carreiras": {"b" * 64}},
        "audit": {
            "registros_divergentes_do_lote": 0,
            "registros_sem_lote": 0,
            "lotes_com_falha": 0,
        },
    }


class AcceptanceContractTests(unittest.TestCase):
    def test_valid_counts_and_integrity(self):
        result = evaluate_snapshot(valid_snapshot())
        self.assertEqual(result["status"], "aprovado")
        self.assertEqual(result["registros_por_fonte"],
                         {"aposentados": 2, "carreiras": 3})
        self.assertNotIn("nome", json.dumps(result))

    def test_inconsistent_batch_counters_fail(self):
        snapshot = valid_snapshot()
        snapshot["data_issues"]["contagem_lote_inconsistente"] = 2
        result = evaluate_snapshot(snapshot)
        self.assertEqual(result["status"], "reprovado")
        self.assertTrue(any("contagem_lote_inconsistente" in e for e in result["erros"]))

    def test_missing_source_is_pending_not_success(self):
        snapshot = valid_snapshot()
        snapshot["sources"]["aposentados"]["registros"] = 0
        result = evaluate_snapshot(snapshot)
        self.assertEqual(result["status"], "pendente")
        self.assertTrue(any("aposentados" in p for p in result["pendencias"]))

    def test_missing_index_or_constraint_fails(self):
        snapshot = valid_snapshot()
        snapshot["indexes"].remove("idx_servidores_nome_similar")
        snapshot["constraints"].pop("servidores_lote_importacao_fk")
        result = evaluate_snapshot(snapshot)
        self.assertEqual(result["status"], "reprovado")
        self.assertEqual(len(result["erros"]), 2)

    def test_integrity_violation_or_missing_column_fails(self):
        snapshot = valid_snapshot()
        snapshot["columns"]["servidores"].remove("uf")
        snapshot["data_issues"]["uf_invalida"] = 1
        snapshot["audit"]["registros_divergentes_do_lote"] = 3
        result = evaluate_snapshot(snapshot)
        self.assertEqual(result["status"], "reprovado")
        self.assertEqual(len(result["erros"]), 3)

    def test_match_and_missing_file_hashes(self):
        snapshot = valid_snapshot()
        self.assertEqual(evaluate_snapshot(snapshot, file_hashes={
            "aposentados": "a" * 64, "carreiras": "b" * 64,
        })["status"], "aprovado")
        result = evaluate_snapshot(snapshot, file_hashes={"aposentados": "f" * 64})
        self.assertEqual(result["status"], "pendente")
        self.assertNotIn("f" * 64, json.dumps(result))

    def test_legacy_rows_and_failed_batches_are_warnings(self):
        snapshot = valid_snapshot()
        snapshot["audit"]["registros_sem_lote"] = 2
        snapshot["audit"]["lotes_com_falha"] = 1
        self.assertEqual(len(evaluate_snapshot(snapshot)["avisos"]), 2)

    def test_schema_absence_prevents_data_queries(self):
        responses = [[], [], [], [(False,)]]
        executed = []

        class Cursor:
            def __init__(self):
                self.i = -1
            def execute(self, sql):
                self.i += 1
                executed.append(sql)
            def fetchall(self):
                return responses[self.i]
            def fetchone(self):
                return responses[self.i][0]
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        cursor = Cursor()
        class SingleCursorConnection:
            def cursor(self):
                return cursor

        result = collect_snapshot(SingleCursorConnection())
        self.assertEqual(result["sources"], {})
        self.assertEqual(len(executed), 4)
        self.assertEqual(evaluate_snapshot(result)["status"], "reprovado")

    def test_checksum_is_streamed(self):
        import hashlib
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "arquivo.csv"
            path.write_bytes(b"dados de teste")
            self.assertEqual(checksum(path), hashlib.sha256(b"dados de teste").hexdigest())


class HttpContractTests(unittest.TestCase):
    @staticmethod
    def mock_urlopen(*, total=2, records=2, healthy=True):
        class Response:
            status = 200
            headers = {"Content-Type": "application/json"}
            def __init__(self, content):
                self.stream = io.BytesIO(json.dumps(content).encode("utf-8"))
            def read(self, n=-1):
                return self.stream.read(n)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        def invoke(url, timeout):
            if url.endswith("/health"):
                return Response({"status": "ok" if healthy else "degraded",
                                 "database": "ok" if healthy else "unavailable"})
            return Response({
                "items": [{"id": n, "nome": "Dado restrito", "cargo": "A",
                           "orgao": "B", "uf": None, "fonte": "carreiras"}
                          for n in range(records)],
                "pagination": {"page": 1, "page_size": 5, "total": total,
                               "pages": 1 if total else 0},
            })
        return invoke

    def test_http_acceptance_does_not_print_names(self):
        with patch("scripts.validate_database.urlopen", self.mock_urlopen()):
            report = check_http("http://backend:5000", 2)
        self.assertEqual(report, {"status": "aprovado", "registros_na_primeira_pagina": 2})
        self.assertNotIn("Dado restrito", json.dumps(report))

    def test_http_rejects_mismatched_count(self):
        with patch("scripts.validate_database.urlopen", self.mock_urlopen(total=3)):
            with self.assertRaises(ValueError):
                check_http("http://localhost:5000/api", 2)

    def test_http_requires_healthy_database(self):
        with patch("scripts.validate_database.urlopen", self.mock_urlopen(healthy=False)):
            with self.assertRaises(ValueError):
                check_http("http://localhost:5000", 2)

    def test_http_blocks_nonlocal_targets(self):
        with self.assertRaises(ValueError):
            check_http("https://example.com", 2)


if __name__ == "__main__":
    unittest.main()
