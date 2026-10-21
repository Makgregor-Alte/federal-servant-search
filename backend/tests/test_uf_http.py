"""Contrato HTTP do filtro de UF com conexão simulada."""
import unittest
from unittest.mock import patch

from app import create_app


class FakeCursor:
    def __init__(self, executed, rows):
        self.executed = executed
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return {"count": len(self.rows)}

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, executed, rows):
        self.cursor_instance = FakeCursor(executed, rows)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self.cursor_instance


class UFHttpTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.testing = True
        self.client = app.test_client()
        self.executed = []

    def test_busca_por_uf_devolve_json_e_parametro_normalizado(self):
        rows = [{"id": 1, "nome": "Maria", "cargo": "Analista", "orgao": "FURG", "uf": "RS", "fonte": "carreira"}]
        with patch("app.routes.connect_db", return_value=FakeConnection(self.executed, rows)):
            response = self.client.get("/api/servidores?uf=rs")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["items"], rows)
        self.assertEqual(response.json["pagination"]["total"], 1)
        self.assertEqual(self.executed[0][1], {"uf": "RS"})
        self.assertIn("uf = %(uf)s", self.executed[0][0])

    def test_filtro_uf_sem_resultados(self):
        with patch("app.routes.connect_db", return_value=FakeConnection(self.executed, [])):
            response = self.client.get("/api/servidores?uf=AC")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["items"], [])
        self.assertEqual(response.json["pagination"]["total"], 0)

    def test_uf_invalida_retorna_400_sem_acessar_banco(self):
        with patch("app.routes.connect_db") as db:
            for query in ("uf=", "uf=%20%20", "uf=XX", "uf=RS%0A", "uf=RS&uf=SP"):
                with self.subTest(query=query):
                    response = self.client.get("/api/servidores?" + query)
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json["error"], "invalid_parameters")
            db.assert_not_called()

    def test_ausencia_de_uf_mantem_registros_sem_estado(self):
        rows = [{"id": 1, "nome": "Maria", "cargo": "", "orgao": "", "uf": None, "fonte": "aposentados"}]
        with patch("app.routes.connect_db", return_value=FakeConnection(self.executed, rows)):
            response = self.client.get("/api/servidores")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json["items"][0]["uf"])
        self.assertNotIn("uf =", self.executed[0][0])


if __name__ == "__main__":
    unittest.main()
