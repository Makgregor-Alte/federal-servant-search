"""Validation and SQL behavior of institution/agency searches."""
import unittest

from app.search import build_search_queries, parse_filters


class AgencySearchTests(unittest.TestCase):
    def test_portuguese_and_frontend_parameters(self):
        for key in ("orgao", "agency"):
            with self.subTest(key=key):
                filters = parse_filters({key: " Universidade "})
                self.assertEqual(filters.agency, "Universidade")
                count_sql, data_sql, params, data_params = build_search_queries(filters)
                self.assertIn("orgao ILIKE %(agency)s ESCAPE '\\'", count_sql)
                self.assertIn("orgao ILIKE %(agency)s ESCAPE '\\'", data_sql)
                self.assertEqual(params["agency"], "%Universidade%")
                self.assertEqual(data_params["agency"], "%Universidade%")
                self.assertNotIn("Universidade", count_sql + data_sql)

    def test_normalizes_unicode_and_internal_whitespace(self):
        filters = parse_filters({"orgao": "  Ministe\u0301rio   da    Educac\u0327a\u0303o  "})
        self.assertEqual(filters.agency, "Ministério da Educação")
        _, _, params, _ = build_search_queries(filters)
        self.assertEqual(params["agency"], "%Ministério da Educação%")

    def test_sql_metacharacters_remain_literal_and_parameterized(self):
        payload = "Universidade%_\\' OR TRUE --"
        count_sql, data_sql, params, _ = build_search_queries(parse_filters({"orgao": payload}))
        self.assertEqual(params["agency"], r"%Universidade\%\_\\' OR TRUE --%")
        self.assertNotIn(payload, count_sql + data_sql)
        self.assertNotIn(" OR TRUE", count_sql + data_sql)

    def test_no_agency_filter_if_not_provided(self):
        count_sql, _, params, _ = build_search_queries(parse_filters({}))
        self.assertNotIn("orgao ILIKE", count_sql)
        self.assertNotIn("agency", params)

    def test_empty_agency_is_rejected(self):
        for args in ({"orgao": ""}, {"orgao": "  "}, {"agency": ""}, {"agency": None}):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, "orgao pesquisado"):
                parse_filters(args)

    def test_invalid_and_ambiguous_agency_inputs(self):
        for args in (
            {"orgao": "A" * 151},
            {"orgao": "Universidade\nFederal"},
            {"agency": "FURG\x00"},
            {"agency": "FURG\x7f"},
            {"orgao": "FURG", "agency": "FURG"},
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                parse_filters(args)

    def test_combined_filters_share_parameterized_query(self):
        args = {"nome": "Ana", "cargo": "Analista", "orgao": "FURG", "uf": "rs", "pagina": "2", "limit": "5"}
        filters = parse_filters(args)
        self.assertEqual((filters.agency, filters.uf, filters.page, filters.page_size), ("FURG", "RS", 2, 5))
        count_sql, data_sql, params, data_params = build_search_queries(filters)
        self.assertEqual(count_sql.count(" AND "), 3)
        self.assertIn("orgao ILIKE %(agency)s ESCAPE '\\'", count_sql)
        self.assertEqual(params["agency"], "%FURG%")
        self.assertEqual(data_params["offset"], 5)
        self.assertIn("LIMIT %(limit)s OFFSET %(offset)s", data_sql)

    def test_unmatched_agency_is_valid_search(self):
        _, _, params, _ = build_search_queries(parse_filters({"orgao": "Instituição inexistente"}))
        self.assertEqual(params["agency"], "%Instituição inexistente%")


if __name__ == "__main__":
    unittest.main()
