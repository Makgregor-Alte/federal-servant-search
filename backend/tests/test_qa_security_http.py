"""Flask security regression tests, skipped when HTTP dependencies are absent."""

import importlib.util
import os
import unittest
from unittest.mock import patch


HAS_HTTP_DEPS = all(importlib.util.find_spec(module) is not None for module in ('flask', 'psycopg'))


@unittest.skipUnless(HAS_HTTP_DEPS, 'Flask and Psycopg are required')
class ApiSecurityTests(unittest.TestCase):
    def setUp(self):
        from app import create_app
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()
        self.origin = 'http://localhost:5173'

    def test_valid_cors_preflight(self):
        with patch.dict(os.environ, {'ALLOWED_ORIGINS': self.origin}):
            response = self.client.options('/api/servidores', headers={
                'Origin': self.origin,
                'Access-Control-Request-Method': 'GET',
                'Access-Control-Request-Headers': 'Content-Type',
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], self.origin)
        self.assertIn('GET', response.headers['Access-Control-Allow-Methods'])
        self.assertIn('Content-Type', response.headers['Access-Control-Allow-Headers'])

    def test_unapproved_methods_and_headers_are_not_authorized(self):
        for method, headers in [('DELETE', ''), ('GET', 'Authorization'), ('POST', 'Content-Type')]:
            with self.subTest(method=method, headers=headers), patch.dict(os.environ, {'ALLOWED_ORIGINS': self.origin}):
                response = self.client.options('/api/servidores', headers={
                    'Origin': self.origin,
                    'Access-Control-Request-Method': method,
                    'Access-Control-Request-Headers': headers,
                })
                self.assertNotIn('Access-Control-Allow-Origin', response.headers)
                self.assertNotIn('Access-Control-Allow-Methods', response.headers)

    def test_headers_are_sent_on_errors(self):
        response = self.client.get('/api/not-a-route')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers.get('Referrer-Policy'), 'no-referrer')
        self.assertEqual(response.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(response.headers.get('Cache-Control'), 'no-store')

    def test_rejected_unknown_parameters_are_not_reflected(self):
        payload = '<script>alert(1)</script>'
        with patch('app.routes.connect_db') as connect:
            response = self.client.get('/api/servidores', query_string={payload: '1'})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.is_json)
        self.assertNotIn(payload, response.get_data(as_text=True))
        connect.assert_not_called()

    def test_query_too_long_is_rejected_before_database_access(self):
        with patch('app.routes.connect_db') as connect:
            response = self.client.get('/api/servidores?' + 'q' * 5000)
        self.assertEqual(response.status_code, 413)
        self.assertTrue(response.is_json)
        connect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
