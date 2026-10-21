"""Validate SPA routes and API forwarding with the deployed Nginx configuration."""

import http.client
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
class FrontendRoutingTests(unittest.TestCase):
    def test_spa_routes_and_api_proxy(self):
        class Backend(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"status":"ok"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
        thread = threading.Thread(target=backend.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="spa_nginx_") as tmp:
                directory = Path(tmp)
                os.chmod(directory, 0o755)
                static = directory / "static"
                static.mkdir()
                (static / "index.html").write_text("<html>frontend-ready</html>", encoding="utf-8")
                with socket.socket() as connection:
                    connection.bind(("127.0.0.1", 0))
                    port = connection.getsockname()[1]
                nginx = (ROOT / "frontend/nginx.conf").read_text(encoding="utf-8")
                nginx = nginx.replace("listen 80;", f"listen 127.0.0.1:{port};")
                nginx = nginx.replace("root /usr/share/nginx/html;", f"root {static};")
                nginx = nginx.replace("http://backend:5000", f"http://127.0.0.1:{backend.server_port}")
                nginx = nginx.replace("/var/log/nginx/access.log", str(directory / "access.log"))
                config = directory / "nginx.conf"
                config.write_text(
                    f"pid {directory / 'nginx.pid'};\nevents {{}}\nhttp {{\n{nginx}\n}}\n",
                    encoding="utf-8",
                )
                checked = subprocess.run(["nginx", "-t", "-c", str(config)], capture_output=True, text=True)
                self.assertEqual(checked.returncode, 0, checked.stderr)
                process = subprocess.Popen(
                    ["nginx", "-c", str(config), "-g", "daemon off;"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                try:
                    for _ in range(40):
                        try:
                            with socket.create_connection(("127.0.0.1", port), timeout=1):
                                break
                        except OSError:
                            time.sleep(0.1)
                    else:
                        self.fail("Nginx did not start")
                    for path in ("/", "/login", "/cadastro", "/sistema"):
                        with self.subTest(path=path):
                            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
                            try:
                                conn.request("GET", path)
                                response = conn.getresponse()
                                self.assertEqual(response.status, 200)
                                self.assertIn(b"frontend-ready", response.read())
                            finally:
                                conn.close()
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
                    try:
                        conn.request("GET", "/api/health")
                        response = conn.getresponse()
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.read(), b'{"status":"ok"}')
                    finally:
                        conn.close()
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
        finally:
            backend.shutdown()
            backend.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
