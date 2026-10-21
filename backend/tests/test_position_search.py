"""Behavior of position/profession search parameters and SQL."""
import unittest

from app.search import build_search_queries, parse_filters


class PositionSearchTests(unittest.TestCase):
    def test_portuguese_and_existing_frontend_parameters(self):
        for key in ("cargo", "position"):
            with self.subTest(key=key):
                filters = parse_filters({key: " Analista "})
                self.assertEqual(filters.position, "Analista")
                count_sql, data_sql, params, data_params = build_search_queries(filters)
                self.assertIn("cargo ILIKE %(position)s ESCAPE '\\'", count_sql)
                self.assertIn("cargo ILIKE %(position)s ESCAPE '\\'", data_sql)
                self.assertEqual(params["position"], "%Analista%")
                self.assertEqual(data_params["position"], "%Analista%")
                self.assertNotIn("Analista", count_sql + data_sql)
                self.assertNotIn("nome)", count_sql)

    def test_search_accepts_case_insensitive_portuguese_job_titles(self):
        filters = parse_filters({"cargo": "  Te\u0301cnico   em   Informática  "})
        self.assertEqual(filters.position, "Técnico em Informática")
        _, _, params, _ = build_search_queries(filters)
        self.assertEqual(params["position"], "%Técnico em Informática%")

    def test_wildcards_and_sql_are_literal_data(self):
        text = "Analista%_\\' OR TRUE --"
        _, data_sql, params, _ = build_search_queries(parse_filters({"cargo": text}))
        self.assertEqual(params["position"], r"%Analista\%\_\\' OR TRUE --%")
        self.assertNotIn(text, data_sql)

    def test_absent_cargo_does_not_filter(self):
        count_sql, _, params, _ = build_search_queries(parse_filters({}))
        self.assertNotIn("cargo ILIKE", count_sql)
        self.assertNotIn("position", params)

    def test_explicitly_empty_cargo_is_rejected(self):
        for args in ({"cargo": ""}, {"cargo": "  "}, {"position": ""}):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, "cargo pesquisado"):
                parse_filters(args)

    def test_invalid_and_ambiguous_cargo_inputs(self):
        for args in (
            {"cargo": "a" * 151},
            {"cargo": "Analista\nAdministrador"},
            {"cargo": "Analista", "position": "Analista"},
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                parse_filters(args)

    def test_no_match_is_valid_query(self):
        _, _, params, _ = build_search_queries(parse_filters({"cargo": "Cargo Inexistente 12345"}))
        self.assertEqual(params["position"], "%Cargo Inexistente 12345%")


if __name__ == "__main__":
    unittest.main()
