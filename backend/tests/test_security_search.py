"""Input validation and parameterized SQL checks."""
import unittest

from app.search import build_search_queries, like_contains, parse_filters


class SecuritySearchTests(unittest.TestCase):
    def test_invisible_unicode_characters_are_rejected(self):
        for payload in ("Ana\u200bSilva", "Ana\u202eSilva", "Ana\x00Silva", "Ana\ud800Silva"):
            with self.subTest(payload=repr(payload)), self.assertRaises(ValueError):
                parse_filters({"nome": payload})

    def test_invisible_unicode_rejected_in_other_text_filters(self):
        for filter_name in ("cargo", "orgao", "similar", "name_mode"):
            with self.subTest(filter_name=filter_name), self.assertRaises(ValueError):
                parse_filters({filter_name: "Engenheiro\u200b"})

    def test_unicode_letters_remain_supported(self):
        filters = parse_filters({"nome": "  Jos\u00e9   de   Souza  ", "cargo": "T\u00e9cnica", "orgao": "Educa\u00e7\u00e3o"})
        self.assertEqual(filters.name, "Jos\u00e9 de Souza")
        self.assertEqual(filters.position, "T\u00e9cnica")
        self.assertEqual(filters.agency, "Educa\u00e7\u00e3o")

    def test_attack_payloads_are_only_bound_parameters(self):
        attacks = ("' OR 1=1 --", "%' UNION SELECT * FROM users--", "x\\' ; DROP TABLE servidores; --")
        for payload in attacks:
            for field in ("nome", "cargo", "orgao", "similar"):
                with self.subTest(field=field, payload=payload):
                    filters = parse_filters({field: payload})
                    count_sql, data_sql, count_params, data_params = build_search_queries(filters)
                    self.assertNotIn(payload, count_sql + data_sql)
                    expected = {
                        "nome": filters.name,
                        "similar": filters.name,
                        "cargo": like_contains(filters.position),
                        "orgao": like_contains(filters.agency),
                    }[field]
                    self.assertIn(expected, count_params.values())
                    self.assertIn(expected, data_params.values())

    def test_unknown_query_parameter_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_filters({"nome": "Ana", "table": "servidores; DROP TABLE x"})

    def test_long_inputs_rejected(self):
        with self.assertRaises(ValueError):
            parse_filters({"orgao": "A" * 151})


if __name__ == "__main__":
    unittest.main()
