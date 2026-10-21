"""Regression tests for fuzzy count and prefix pagination."""
import unittest

from app.search import build_fuzzy_prefix_page, build_search_queries, parse_filters


class FuzzyFastPathSqlTests(unittest.TestCase):
    def test_union_counts_all_candidates_by_unique_id(self):
        f = parse_filters({"similar": "Mariana", "page": "1", "page_size": "20"})
        count_sql, original_page, count_params, page_params = build_search_queries(f)
        self.assertEqual(count_sql.count("SELECT id FROM servidores WHERE"), 2)
        self.assertIn(" UNION ", count_sql)
        self.assertIn("AS matched_ids", count_sql)
        self.assertIn("LOWER(nome) %% LOWER(%(name)s)", count_sql)
        self.assertIn("LOWER(nome) LIKE LOWER(%(name_pattern)s)", count_sql)
        self.assertNotIn("LIMIT", count_sql)
        self.assertEqual(count_params["name_pattern"], "%Mariana%")
        self.assertIn("ORDER BY CASE", original_page)
        self.assertEqual(page_params["offset"], 0)

    def test_prefix_path_preserves_order_and_offset(self):
        f = parse_filters({"similar": "Mariana", "page": "3", "limit": "10"})
        _, original_page, _, original_params = build_search_queries(f)
        prefix_page, params = build_fuzzy_prefix_page(f)
        self.assertIn("LOWER(nome) LIKE LOWER(%(name_prefix)s)", prefix_page)
        self.assertNotIn("OR LOWER(nome) LIKE LOWER(%(name_pattern)s) ESCAPE", prefix_page.split("ORDER BY")[0])
        self.assertEqual(prefix_page.split("ORDER BY", 1)[1], original_page.split("ORDER BY", 1)[1])
        self.assertEqual(params, original_params)
        self.assertEqual(params["offset"], 20)
        self.assertEqual(params["limit"], 10)
        self.assertEqual(params["name_prefix"], "Mariana%")

    def test_combined_searches_keep_old_paths(self):
        for extra in ({"uf": "RS"}, {"cargo": "Analista"}, {"orgao": "Federal"}):
            with self.subTest(extra=extra):
                f = parse_filters({"similar": "Mariana", **extra})
                count_sql, _, _, _ = build_search_queries(f)
                self.assertNotIn(" UNION ", count_sql)
                self.assertIsNone(build_fuzzy_prefix_page(f))

    def test_non_fuzzy_queries_are_unmodified(self):
        for query in ({}, {"nome": "Mariana"}, {"similar": "ANA%SILVA%"}):
            with self.subTest(query=query):
                f = parse_filters(query)
                self.assertIsNone(build_fuzzy_prefix_page(f))
                self.assertNotIn(" UNION ", build_search_queries(f)[0])

    def test_prefix_escaping_is_parameterized(self):
        f = parse_filters({"name": "Jo%_\\", "name_mode": "similar"})
        result = build_fuzzy_prefix_page(f)
        self.assertIsNotNone(result)
        sql, params = result
        self.assertEqual(params["name_prefix"], r"Jo\%\_\\%")
        self.assertNotIn(f.name, sql)


if __name__ == "__main__":
    unittest.main()
