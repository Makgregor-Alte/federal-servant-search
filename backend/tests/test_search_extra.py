"""Additional search semantics and SQL-injection regression tests."""
import unittest
from app.search import build_search_queries, like_contains, parse_filters


class SearchContractTests(unittest.TestCase):
    def test_similar_mode_also_matches_name_substrings(self):
        filt = parse_filters({"name": "Maria", "name_mode": "similar"})
        count, data, params, data_params = build_search_queries(filt)
        self.assertIn("LOWER(nome) LIKE LOWER(%(name_pattern)s)", count)
        self.assertIn("similarity(", data)
        self.assertEqual(params["name_pattern"], "%Maria%")
        self.assertEqual(data_params["name_pattern"], "%Maria%")

    def test_like_characters_are_not_wildcards_in_name(self):
        filt = parse_filters({"name": r"Ana%_\\", "name_mode": "similar"})
        count, data, params, _ = build_search_queries(filt)
        self.assertEqual(params["name_pattern"], like_contains(r"Ana%_\\"))
        self.assertNotIn(r"Ana%_\\", count + data)

    def test_combined_filters_remain_parameterized(self):
        value = "Maria' OR 1=1 --"
        filt = parse_filters({"name": value, "agency": "FURG", "uf": "RS"})
        count, data, params, result_params = build_search_queries(filt)
        self.assertNotIn(value, count + data)
        self.assertEqual(params["name"], value)
        self.assertEqual(result_params["uf"], "RS")


if __name__ == "__main__":
    unittest.main()
