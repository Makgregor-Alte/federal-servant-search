import unittest
from app.search import build_search_queries, like_contains, pagination, parse_filters


class SearchTests(unittest.TestCase):
    def test_defaults(self):
        filt = parse_filters({})
        self.assertEqual((filt.page, filt.page_size, filt.name_mode), (1, 20, "exact"))

    def test_invalid_pagination(self):
        for args in ({"page": "0"}, {"page_size": "101"}, {"page": "abc"}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                parse_filters(args)

    def test_uf(self):
        self.assertEqual(parse_filters({"uf": "rs"}).uf, "RS")
        with self.assertRaises(ValueError):
            parse_filters({"uf": "ZZ"})

    def test_exact_search_uses_parameters(self):
        f = parse_filters({"name": "O'Neil", "uf": "RS"})
        count, query, params, page_params = build_search_queries(f)
        self.assertIn("LOWER(nome) = LOWER(%(name)s)", count)
        self.assertNotIn("O'Neil", query)
        self.assertEqual(page_params["name"], "O'Neil")

    def test_similarity_uses_trgm(self):
        f = parse_filters({"name": "Maria", "name_mode": "similar"})
        _, query, _, _ = build_search_queries(f)
        self.assertIn("LOWER(nome) %% LOWER(%(name)s)", query)
        self.assertIn("similarity(", query)

    def test_filter_literal_wildcards(self):
        self.assertEqual(like_contains(r"100%_x\z"), r"%100\%\_x\\z%")

    def test_pagination(self):
        self.assertEqual(pagination(21, parse_filters({"page_size": "20"}))["pages"], 2)

    def test_combined_filters_and_offset(self):
        filt = parse_filters({"name": "Ana", "position": "Analista", "agency": "FURG", "uf": "RS", "page": "3", "page_size": "5"})
        count, data, params, data_params = build_search_queries(filt)
        self.assertEqual(count.count(" AND "), 3)
        self.assertIn("LIMIT %(limit)s OFFSET %(offset)s", data)
        self.assertEqual((data_params["limit"], data_params["offset"]), (5, 10))
        self.assertEqual(params["uf"], "RS")

    def test_long_input_and_invalid_mode(self):
        with self.assertRaises(ValueError):
            parse_filters({"name": "a"*151})
        with self.assertRaises(ValueError):
            parse_filters({"name_mode": "unknown"})


if __name__ == "__main__":
    unittest.main()
