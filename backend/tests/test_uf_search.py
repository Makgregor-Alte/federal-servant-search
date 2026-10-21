"""Validação e construção de consultas por unidade federativa."""
import unittest

from app.search import UF_VALIDAS, build_search_queries, parse_filters


class UFSearchTests(unittest.TestCase):
    def test_todas_as_unidades_federativas(self):
        self.assertEqual(len(UF_VALIDAS), 27)
        for sigla in sorted(UF_VALIDAS):
            with self.subTest(sigla=sigla):
                filters = parse_filters({"uf": sigla.lower()})
                self.assertEqual(filters.uf, sigla)
                count_sql, data_sql, params, data_params = build_search_queries(filters)
                self.assertIn("uf = %(uf)s", count_sql)
                self.assertIn("uf = %(uf)s", data_sql)
                self.assertEqual(params, {"uf": sigla})
                self.assertEqual(data_params["uf"], sigla)
                self.assertNotIn(f"uf = '{sigla}'", data_sql)

    def test_uf_com_espacos_e_letras_minusculas(self):
        self.assertEqual(parse_filters({"uf": "  rS  "}).uf, "RS")
        self.assertEqual(parse_filters({"uf": "sP"}).uf, "SP")

    def test_sem_filtro_de_uf_nao_restringe_resultados(self):
        filters = parse_filters({})
        self.assertEqual(filters.uf, "")
        count_sql, data_sql, params, data_params = build_search_queries(filters)
        self.assertNotIn("uf =", count_sql)
        self.assertNotIn("uf =", data_sql)
        self.assertNotIn("uf", params)
        self.assertNotIn("uf", data_params)

    def test_uf_invalida_e_uf_vazia(self):
        invalidos = (
            "", "   ", "XX", "R", "RSS", "S1", "1S", "R S", "RS,SP",
            "RS\n", "\tSP", "ſP", "' OR 1=1 --",
        )
        for uf in invalidos:
            with self.subTest(uf=uf), self.assertRaises(ValueError):
                parse_filters({"uf": uf})
        with self.assertRaises(ValueError):
            parse_filters({"uf": None})

    def test_uf_em_busca_combinada(self):
        filters = parse_filters({"uf": "RS", "nome": "Maria", "cargo": "Analista"})
        count_sql, _, params, _ = build_search_queries(filters)
        self.assertIn("uf = %(uf)s", count_sql)
        self.assertIn("cargo ILIKE %(position)s", count_sql)
        self.assertIn("LOWER(nome) = LOWER(%(name)s)", count_sql)
        self.assertEqual(params["uf"], "RS")


if __name__ == "__main__":
    unittest.main()
