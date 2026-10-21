"""Security checks for request validation, proxy configuration and SQL parameters."""

import json
from pathlib import Path
import unittest

from app.search import build_search_queries, like_contains, parse_filters


ROOT = Path(__file__).resolve().parents[2]


class SecurityHardeningTests(unittest.TestCase):
    def test_unknown_parameter_names_are_not_reflected(self):
        marker = '<svg onload=alert(1)>'
        with self.assertRaises(ValueError) as captured:
            parse_filters({marker: 'x'})
        self.assertNotIn(marker, str(captured.exception))

    def test_sql_injection_is_never_inserted_into_query_text(self):
        attack = "' UNION SELECT pg_sleep(5)--"
        for key in ('nome', 'cargo', 'orgao'):
            with self.subTest(key=key):
                count_sql, data_sql, params, data_params = build_search_queries(parse_filters({key: attack}))
                self.assertNotIn(attack, count_sql)
                self.assertNotIn(attack, data_sql)
                expected = attack if key == 'nome' else like_contains(attack)
                self.assertIn(expected, params.values())
                self.assertIn(expected, data_params.values())

    def test_proxy_does_not_trust_forwarded_client_ip(self):
        nginx = (ROOT / 'frontend/nginx.conf').read_text(encoding='utf-8')
        self.assertIn('proxy_set_header X-Forwarded-For $remote_addr;', nginx)
        self.assertNotIn('proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;', nginx)

    def test_proxy_hides_version_and_limits_request_bodies(self):
        nginx = (ROOT / 'frontend/nginx.conf').read_text(encoding='utf-8')
        self.assertIn('server_tokens off;', nginx)
        self.assertIn('client_max_body_size 4k;', nginx)

    def test_proxy_oversized_rejections_are_json(self):
        nginx = (ROOT / 'frontend/nginx.conf').read_text(encoding='utf-8')
        self.assertIn('error_page 413 = @request_too_large;', nginx)
        for status, name in ((413, 'request_too_large'),):
            start = nginx.index('location @' + name + ' {')
            end = nginx.index('\n    }', start)
            block = nginx[start:end]
            self.assertIn(f'return {status} ', block)
            self.assertIn('application/json', block)
            self.assertIn('nosniff', block)
            body = block.split(f'return {status} ', 1)[1].split("'", 2)[1]
            self.assertIn('error', json.loads(body))

    def test_http_access_logs_do_not_log_search_parameters(self):
        nginx = (ROOT / 'frontend/nginx.conf').read_text(encoding='utf-8')
        access_format = next(line for line in nginx.splitlines() if line.startswith('log_format safe_access'))
        self.assertIn('$uri', access_format)
        self.assertNotIn('$request_uri', access_format)
        self.assertNotIn('$args', access_format)
        self.assertNotIn('$request ', access_format)


if __name__ == '__main__':
    unittest.main()
