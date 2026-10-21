"""Validation and SQL contract for paginated servant searches."""
import unittest

from app.search import build_search_queries, pagination, parse_filters


class PaginationSearchTests(unittest.TestCase):
    def test_defaults_and_portuguese_aliases(self):
        default = parse_filters({})
        custom = parse_filters({"pagina": "2", "limit": "100"})
        self.assertEqual((default.page, default.page_size), (1, 20))
        self.assertEqual((custom.page, custom.page_size), (2, 100))

    def test_minimum_and_maximum_page_size(self):
        for size in ("1", "20", "100"):
            with self.subTest(size=size):
                self.assertEqual(parse_filters({"limit": size}).page_size, int(size))

    def test_empty_numeric_parameters_are_invalid(self):
        for key in ("page", "pagina", "page_size", "limit"):
            for value in ("", "  "):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    parse_filters({key: value})

    def test_malformed_numeric_parameters_are_invalid(self):
        for key, value in (
            ("page", "0"), ("page", "-1"), ("page", "1.5"),
            ("page", "1_0"), ("page", "+2"), ("page", "9999999"),
            ("pagina", "abc"), ("page_size", "0"), ("limit", "101"),
            ("limit", "NaN"), ("page_size", "١"),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                parse_filters({key: value})

    def test_duplicate_aliases_are_invalid(self):
        for values in (
            {"page": "1", "pagina": "1"},
            {"limit": "20", "page_size": "20"},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                parse_filters(values)

    def test_page_count_rounding_and_empty(self):
        filt = parse_filters({"limit": "20", "page": "2"})
        self.assertEqual(pagination(0, filt), {
            "page": 2, "page_size": 20, "total": 0, "pages": 0,
        })
        self.assertEqual(pagination(40, filt)["pages"], 2)
        self.assertEqual(pagination(41, filt)["pages"], 3)

    def test_offset_boundaries(self):
        for page, size, offset in ((1, 20, 0), (2, 20, 20), (3, 10, 20), (100, 100, 9900)):
            with self.subTest(page=page, size=size):
                f = parse_filters({"pagina": str(page), "limit": str(size)})
                count_sql, data_sql, count_params, data_params = build_search_queries(f)
                self.assertEqual((data_params["limit"], data_params["offset"]), (size, offset))
                self.assertNotIn("LIMIT", count_sql)
                self.assertIn("LIMIT %(limit)s OFFSET %(offset)s", data_sql)
                self.assertEqual(count_params, {})

    def test_case_insensitive_stable_order_by_id(self):
        exact = build_search_queries(parse_filters({"cargo": "Analista"}))[1]
        fuzzy = build_search_queries(parse_filters({"similar": "Maria"}))[1]
        self.assertIn("ORDER BY LOWER(nome), id LIMIT", exact)
        self.assertIn("similarity(LOWER(nome), LOWER(%(name)s)) DESC, LOWER(nome), id", fuzzy)

    def test_filters_are_kept_in_both_queries(self):
        f = parse_filters({"nome": "Ana", "cargo": "Analista", "uf": "RS", "pagina": "2", "limit": "5"})
        count_sql, data_sql, count_params, data_params = build_search_queries(f)
        self.assertIn("uf = %(uf)s", count_sql)
        self.assertIn("uf = %(uf)s", data_sql)
        self.assertEqual(count_params, {k: v for k, v in data_params.items() if k not in ("limit", "offset")})


if __name__ == "__main__":
    unittest.main()
