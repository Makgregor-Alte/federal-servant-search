"""Nginx hardening smoke test using an isolated local backend."""

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("nginx"), "Nginx required")
class NginxSecuritySmokeTests(unittest.TestCase):
    def test_client_ip_and_oversized_requests(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                payload = json.dumps({"client_ip": self.headers.get("X-Forwarded-For")}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                pass

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=upstream.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory(prefix="proxy_nginx_test_") as temporary:
                directory = Path(temporary)
                with socket.socket() as listener:
                    listener.bind(("127.0.0.1", 0))
                    port = listener.getsockname()[1]
                nginx = (ROOT / "frontend/nginx.conf").read_text(encoding="utf-8")
                nginx = nginx.replace("listen 80;", f"listen 127.0.0.1:{port};")
                nginx = nginx.replace("http://backend:5000", f"http://127.0.0.1:{upstream.server_port}")
                nginx = nginx.replace("/var/log/nginx/access.log", str(directory / "access.log"))
                config = directory / "nginx.conf"
                config.write_text(
                    f"pid {directory / 'nginx.pid'};\nevents {{}}\nhttp {{\n{nginx}\n}}\n",
                    encoding="utf-8",
                )
                check = subprocess.run(
                    ["nginx", "-t", "-c", str(config)], capture_output=True, text=True,
                )
                self.assertEqual(check.returncode, 0, check.stderr)
                process = subprocess.Popen(
                    ["nginx", "-c", str(config), "-g", "daemon off;"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                try:
                    for _ in range(40):
                        try:
                            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                            connection.connect()
                            connection.close()
                            break
                        except OSError:
                            time.sleep(.1)
                    else:
                        self.fail("Nginx did not start")

                    def request(method, uri, body=None, headers=None):
                        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
                        try:
                            connection.request(method, uri, body, headers or {})
                            response = connection.getresponse()
                            return response.status, dict(response.getheaders()), response.read()
                        finally:
                            connection.close()

                    status, headers, body = request(
                        "GET", "/api/servidores?nome=EXAMPLE_PRIVATE_QUERY",
                        headers={"X-Forwarded-For": "192.0.2.123"},
                    )
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(body)["client_ip"], "127.0.0.1")
                    self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")
                    status, headers, body = request("POST", "/api/servidores", "x" * 5000)
                    self.assertEqual(status, 413)
                    self.assertEqual(json.loads(body)["error"], "http_error")
                    self.assertIn("application/json", headers.get("Content-Type", ""))
                    status, _, _ = request("GET", "/api/servidores?" + "x" * 18000)
                    self.assertEqual(status, 414)
                    access = (directory / "access.log").read_text(encoding="utf-8")
                    self.assertNotIn("EXAMPLE_PRIVATE_QUERY", access)
                    self.assertNotIn("192.0.2.123", access)
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
        finally:
            upstream.shutdown()
            upstream.server_close()
            worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
