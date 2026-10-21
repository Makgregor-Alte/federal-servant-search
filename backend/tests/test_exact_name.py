"""Acceptance checks for exact full-name search."""
import unittest

from app.search import build_search_queries, parse_filters


class ExactNameTests(unittest.TestCase):
    def test_exact_uses_portuguese_alias_and_normalizes_spaces(self):
        filters = parse_filters({"nome": "  Maria   da   Silva  "})
        self.assertEqual(filters.name_mode, "exact")
        self.assertEqual(filters.name, "Maria da Silva")

    def test_exact_normalizes_unicode_composition(self):
        filters = parse_filters({"name": " Jose\u0301  da  Silva "})
        self.assertEqual(filters.name, "José da Silva")

    def test_exact_uses_equality_not_like_or_similarity(self):
        filters = parse_filters({"nome": "Maria da Silva", "uf": "RS"})
        count, data, params, paging = build_search_queries(filters)
        self.assertIn("LOWER(nome) = LOWER(%(name)s)", count)
        self.assertIn("uf = %(uf)s", count)
        self.assertNotIn("LIKE", count)
        self.assertNotIn("similarity(", data)
        self.assertEqual(params, {"name": "Maria da Silva", "uf": "RS"})
        self.assertEqual(paging["limit"], 20)

    def test_exact_treats_percent_and_underscore_as_literal(self):
        value = "Ana_% Silva"
        count, data, params, paging = build_search_queries(parse_filters({"name": value}))
        self.assertIn("LOWER(nome) = LOWER(%(name)s)", count)
        self.assertNotIn("LIKE", count)
        self.assertNotIn(value, count + data)
        self.assertEqual(params["name"], value)
        self.assertEqual(paging["name"], value)

    def test_blank_name_is_invalid_if_explicitly_provided(self):
        for params in ({"name": ""}, {"nome": "   "}, {"similar": ""}, {"name_mode": "exact"}):
            with self.subTest(params=params), self.assertRaisesRegex(ValueError, "vazio"):
                parse_filters(params)

    def test_filterless_listing_remains_supported(self):
        filters = parse_filters({"page": "2", "page_size": "10"})
        count, _, params, paging = build_search_queries(filters)
        self.assertEqual(count, "SELECT COUNT(*) FROM servidores")
        self.assertEqual(params, {})
        self.assertEqual(paging["offset"], 10)

    def test_exact_does_not_change_similar_or_pattern_modes(self):
        similar = parse_filters({"name": " Maria  de  Souza ", "name_mode": "similar"})
        pattern = parse_filters({"similar": "Maria%Souza"})
        self.assertEqual(similar.name, "Maria  de  Souza")
        self.assertEqual(pattern.name_mode, "pattern")
        self.assertEqual(pattern.name, "Maria%Souza")

    def test_injection_cannot_modify_the_sql_text(self):
        attempt = "Ana' OR 1=1 --"
        count, query, params, _ = build_search_queries(parse_filters({"nome": attempt}))
        self.assertNotIn(attempt, count + query)
        self.assertEqual(params["name"], attempt)


if __name__ == "__main__":
    unittest.main()
