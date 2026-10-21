"""Acceptance checks for search query parameters defined by the assignment."""
import unittest
from app.search import build_search_queries, like_pattern, parse_filters


class MultiDict(dict):
    def __init__(self, pairs):
        super().__init__()
        self.values = {}
        for key, value in pairs:
            self.values.setdefault(key, []).append(value)
            self[key] = value

    def getlist(self, key):
        return self.values.get(key, [])


class QueryContractTests(unittest.TestCase):
    def test_portuguese_names_and_combined_filters(self):
        f = parse_filters({"nome": "Maria", "cargo": "Tecnica", "orgao": "Universidade", "uf": "rs"})
        self.assertEqual((f.name, f.position, f.agency, f.uf),
                         ("Maria", "Tecnica", "Universidade", "RS"))
        count, query, count_params, data_params = build_search_queries(f)
        self.assertIn("LOWER(nome) = LOWER(%(name)s)", count)
        self.assertEqual(count.count(" AND "), 3)
        self.assertEqual(count_params["uf"], "RS")
        self.assertEqual(data_params["limit"], 20)
        self.assertNotIn("Tecnica", query)

    def test_examples_with_wildcard_patterns(self):
        for value in ("%NOME%SOBRENOME%", "NOME SOBRENOME%", "NOME%SOBRENOME"):
            with self.subTest(value=value):
                f = parse_filters({"similar": value, "limit": "100"})
                self.assertEqual((f.name_mode, f.page_size), ("pattern", 100))
                count, query, params, _ = build_search_queries(f)
                self.assertIn("LIKE LOWER(%(name_pattern)s)", count)
                self.assertEqual(params["name_pattern"], value)
                self.assertNotIn(value, query)

    def test_similarity_without_wildcards_remains_fuzzy(self):
        f = parse_filters({"similar": "Mariana"})
        self.assertEqual(f.name_mode, "similar")
        self.assertIn("%% LOWER", build_search_queries(f)[0])

    def test_limit_and_page_aliases(self):
        f = parse_filters({"pagina": "3", "limit": "5"})
        self.assertEqual((f.page, f.page_size), (3, 5))
        self.assertEqual(build_search_queries(f)[3]["offset"], 10)

    def test_modern_parameters_remain_supported(self):
        f = parse_filters({"name": "Ana", "name_mode": "similar", "page_size": "15"})
        self.assertEqual((f.name, f.name_mode, f.page_size), ("Ana", "similar", 15))

    def test_invalid_or_ambiguous_parameters(self):
        cases = [
            {"nome": "Ana", "name": "Ana"},
            {"limit": "101"},
            {"similar": "%"},
            {"similar": "Maria", "name_mode": "similar"},
            {"uf": "XX"},
            {"sort": "id"},
            {"nome": "Ana\x00Silva"},
            MultiDict([("uf", "RS"), ("uf", "SP")]),
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                parse_filters(case)

    def test_escaped_underscore_not_a_pattern_wildcard(self):
        self.assertEqual(like_pattern(r"ANA_B%SILVA"), r"ANA\_B%SILVA")

    def test_sql_injection_attempt_stays_as_parameter(self):
        injected = "Maria%' OR 1=1 --"
        f = parse_filters({"similar": injected, "cargo": "Analista"})
        count, data, count_params, _ = build_search_queries(f)
        self.assertNotIn(injected, count + data)
        self.assertEqual(count_params["name_pattern"], injected)


if __name__ == "__main__":
    unittest.main()
