"""Unit tests for intersecting search criteria."""
import unittest

from app.search import build_search_queries, parse_filters


class CombinedSearchTests(unittest.TestCase):
    def test_all_filters_share_one_where_clause_and_and_semantics(self):
        variants = (
            ({"nome": "Maria Silva", "cargo": "Analista", "orgao": "Universidade", "uf": "RS"},
             "LOWER(nome) = LOWER(%(name)s)"),
            ({"name": "Maria Silva", "name_mode": "similar", "position": "Analista",
              "agency": "Universidade", "uf": "RS"},
             "(LOWER(nome) %% LOWER(%(name)s)"),
            ({"similar": "MAR%SILVA%", "cargo": "Analista", "orgao": "Universidade", "uf": "RS"},
             "LOWER(nome) LIKE LOWER(%(name_pattern)s)"),
        )
        for args, name_condition in variants:
            with self.subTest(args=args):
                count, data, count_params, data_params = build_search_queries(parse_filters(args))
                self.assertIn(name_condition, count)
                self.assertIn("cargo ILIKE %(position)s", count)
                self.assertIn("orgao ILIKE %(agency)s", count)
                self.assertIn("uf = %(uf)s", count)
                self.assertEqual(count.count(" AND "), 3)
                self.assertEqual(count.split(" FROM servidores", 1)[1],
                                 data.split(" FROM servidores", 1)[1].split(" ORDER BY ", 1)[0])
                self.assertEqual({k: v for k, v in data_params.items() if k not in ("limit", "offset")},
                                 count_params)

    def test_pairwise_combinations(self):
        args = {"nome": "Maria", "cargo": "Analista", "orgao": "Universidade", "uf": "RS"}
        for keys in (("nome", "cargo"), ("cargo", "uf"), ("orgao", "uf"),
                     ("nome", "orgao"), ("cargo", "orgao"), ("nome", "uf")):
            with self.subTest(keys=keys):
                filters = parse_filters({k: args[k] for k in keys})
                count_sql, data_sql, count_params, data_params = build_search_queries(filters)
                self.assertEqual(count_sql.count(" AND "), 1)
                self.assertEqual(len(count_params), 2)
                self.assertTrue(set(count_params).issubset(set(data_params)))
                self.assertNotIn("Maria", count_sql + data_sql)
                self.assertNotIn("Analista", count_sql + data_sql)
                self.assertNotIn("Universidade", count_sql + data_sql)

    def test_fuzzy_or_is_grouped_before_combining_other_filters(self):
        count, data, params, _ = build_search_queries(parse_filters({
            "similar": "Mariana", "cargo": "Analista", "uf": "RS"}))
        self.assertIn("OR LOWER(nome) LIKE LOWER(%(name_pattern)s) ESCAPE '\\') AND cargo", count)
        self.assertIn("AND uf = %(uf)s", count)
        self.assertEqual(count.count(" OR "), 1)
        self.assertEqual(count.count(" AND "), 2)
        self.assertIn("similarity(", data)
        self.assertEqual(params["position"], "%Analista%")

    def test_name_unicode_and_whitespace_normalization_in_combined_similar_mode(self):
        filters = parse_filters({"nome": "  María    Silva  ", "name_mode": "similar",
                                 "cargo": "  Técnico   de    Sistemas ", "uf": "rs"})
        self.assertEqual(filters.name, "María    Silva")
        self.assertEqual(filters.position, "Técnico de Sistemas")
        self.assertEqual(filters.uf, "RS")
        _, _, params, _ = build_search_queries(filters)
        self.assertEqual(params["name_pattern"], "%María    Silva%")

    def test_pattern_normalizes_unicode_without_rewriting_wildcard_structure(self):
        f = parse_filters({"similar": "  María%Silva%  ", "cargo": "Analista"})
        self.assertEqual(f.name, "María%Silva%")
        _, _, params, _ = build_search_queries(f)
        self.assertEqual(params["name_pattern"], "María%Silva%")

    def test_literal_wildcards_and_injection_remain_parameters_in_mixed_query(self):
        args = {"similar": "%ANA%' OR TRUE --", "cargo": "100%_Analista",
                "orgao": "FURG\\_UNIDADE", "uf": "SP"}
        _, data_sql, params, data_params = build_search_queries(parse_filters(args))
        self.assertNotIn("OR TRUE --", data_sql)
        self.assertNotIn("100%_Analista", data_sql)
        self.assertNotIn("FURG", data_sql)
        self.assertEqual(params["name_pattern"], args["similar"])
        self.assertEqual(params["position"], r"%100\%\_Analista%")
        self.assertEqual(params["agency"], r"%FURG\\\_UNIDADE%")
        self.assertEqual(data_params["uf"], "SP")

    def test_invalid_mixed_inputs_fail_before_sql_construction(self):
        bad = (
            {"nome": "Maria", "name": "Maria", "cargo": "Analista"},
            {"nome": "Maria", "similar": "%Maria%", "uf": "RS"},
            {"nome": "Maria", "cargo": "Analista", "position": "Analista"},
            {"cargo": "Analista", "agency": "FURG", "orgao": "FURG"},
            {"nome": "Maria", "uf": "XX"},
            {"nome": "Maria", "orgao": ""},
        )
        for args in bad:
            with self.subTest(args=args), self.assertRaises(ValueError):
                parse_filters(args)

    def test_all_filters_use_same_pagination_offset(self):
        filters = parse_filters({"similar": "MAR%SILVA%", "cargo": "Analista",
                                 "orgao": "Universidade", "uf": "RS",
                                 "pagina": "4", "limit": "7"})
        _, data_sql, _, data_params = build_search_queries(filters)
        self.assertEqual((data_params["limit"], data_params["offset"]), (7, 21))
        self.assertTrue(data_sql.endswith("LIMIT %(limit)s OFFSET %(offset)s"))


if __name__ == "__main__":
    unittest.main()
