import unittest

from app.search import build_search_queries, like_pattern, parse_filters


class SimilarNameTests(unittest.TestCase):
    def test_examples_from_assignment_preserve_wildcards(self):
        patterns = ("%NOME%SOBRENOME%", "NOME SOBRENOME%", "NOME%SOBRENOME")
        for pattern in patterns:
            with self.subTest(pattern=pattern):
                filters = parse_filters({"similar": pattern, "limit": "100"})
                count_sql, data_sql, params, page_params = build_search_queries(filters)
                self.assertEqual(filters.name_mode, "pattern")
                self.assertEqual(params["name_pattern"], pattern)
                self.assertEqual(page_params["limit"], 100)
                self.assertIn("LIKE LOWER(%(name_pattern)s)", count_sql)
                self.assertNotIn(pattern, count_sql + data_sql)

    def test_pattern_filters_before_sorting_without_changing_count(self):
        filt = parse_filters({"similar": "ANA%SILVA%", "page": "2", "limit": "7"})
        count_sql, data_sql, count_params, data_params = build_search_queries(filt)
        self.assertTrue(count_sql.startswith("SELECT COUNT(*) FROM servidores WHERE "))
        self.assertIn("WITH matched AS MATERIALIZED (SELECT id, nome, cargo, orgao, uf, fonte FROM servidores", data_sql)
        self.assertIn("FROM matched ORDER BY LOWER(nome), id", data_sql)
        self.assertIn("LIKE LOWER(%(name_pattern)s) ESCAPE '\\'", data_sql)
        self.assertEqual(count_params["name_pattern"], "ANA%SILVA%")
        self.assertEqual((data_params["limit"], data_params["offset"]), (7, 7))
        self.assertTrue(data_sql.endswith("LIMIT %(limit)s OFFSET %(offset)s"))

    def test_combined_pattern_keeps_original_filter_intersection(self):
        filt = parse_filters({"similar": "ANA%SILVA%", "cargo": "Analista", "uf": "RS"})
        count_sql, data_sql, _c, _d = build_search_queries(filt)
        self.assertNotIn("WITH matched", data_sql)
        self.assertIn(" AND cargo ILIKE ", count_sql)
        self.assertIn(" AND uf = %(uf)s", data_sql)

    def test_escaped_percent_is_a_literal_not_a_wildcard(self):
        filters = parse_filters({"similar": r"ANA\%%"})
        _, data_sql, params, _ = build_search_queries(filters)
        self.assertEqual(params["name_pattern"], r"ANA\%%")
        self.assertIn("ESCAPE '\\'", data_sql)

    def test_underscore_and_backslash_are_literal(self):
        self.assertEqual(like_pattern(r"ANA_%SILVA"), r"ANA\_%SILVA")
        self.assertEqual(like_pattern(r"ANA\_SILVA"), r"ANA\_SILVA")
        self.assertEqual(like_pattern(r"ANA\\SILVA"), r"ANA\\SILVA")
        self.assertEqual(like_pattern(r"ANA\z%"), r"ANA\\z%")

    def test_fuzzy_matches_names_and_substrings(self):
        filters = parse_filters({"similar": "Maria"})
        count_sql, data_sql, params, page_params = build_search_queries(filters)
        self.assertIn("LOWER(nome) %% LOWER(%(name)s)", count_sql)
        self.assertIn("LIKE LOWER(%(name_pattern)s)", count_sql)
        self.assertEqual(params["name_pattern"], "%Maria%")
        self.assertEqual(params["name_prefix"], "Maria%")
        self.assertEqual(page_params["name_prefix"], "Maria%")
        self.assertIn("similarity(LOWER(nome), LOWER(%(name)s)) DESC", data_sql)

    def test_fuzzy_result_priority_is_exact_then_prefix_then_substring(self):
        _, data_sql, _, _ = build_search_queries(
            parse_filters({"name": "Maria", "name_mode": "similar"})
        )
        self.assertLess(data_sql.index("THEN 0"), data_sql.index("THEN 1"))
        self.assertLess(data_sql.index("THEN 1"), data_sql.index("THEN 2"))
        self.assertLess(data_sql.index("THEN 2"), data_sql.index("ELSE 3"))
        self.assertTrue(data_sql.endswith("LIMIT %(limit)s OFFSET %(offset)s"))

    def test_literal_wildcards_in_fuzzy_mode_are_escaped(self):
        filters = parse_filters({"name": "Jo%_\\", "name_mode": "similar"})
        _, _, params, _ = build_search_queries(filters)
        self.assertEqual(params["name_pattern"], r"%Jo\%\_\\%")
        self.assertEqual(params["name_prefix"], r"Jo\%\_\\%")

    def test_limit_and_invalid_pattern(self):
        with self.assertRaises(ValueError):
            parse_filters({"similar": "%%", "limit": "100"})
        with self.assertRaises(ValueError):
            parse_filters({"similar": "%ANA%", "limit": "101"})
        self.assertEqual(parse_filters({"similar": "%ANA%", "limit": "100"}).page_size, 100)

    def test_combined_filters_remain_parameterized(self):
        injection = "%ANA%' OR TRUE --"
        filters = parse_filters({"similar": injection, "cargo": "Analista", "uf": "RS"})
        count_sql, data_sql, params, page_params = build_search_queries(filters)
        self.assertNotIn(injection, count_sql + data_sql)
        self.assertEqual(params["name_pattern"], injection)
        self.assertEqual(page_params["uf"], "RS")
        self.assertEqual(page_params["position"], "%Analista%")


if __name__ == "__main__":
    unittest.main()
