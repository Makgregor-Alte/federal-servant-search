"""Runtime access logging must not include search query strings."""
import json
import unittest
from pathlib import Path


class RuntimeSecurityTests(unittest.TestCase):
    def test_gunicorn_access_log_omits_query_string(self):
        dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
        command = next(line.removeprefix("CMD ") for line in dockerfile.splitlines() if line.startswith("CMD "))
        args = json.loads(command)
        format_string = args[args.index("--access-logformat") + 1]
        self.assertIn("%(U)s", format_string)
        self.assertNotIn("%(r)s", format_string)
        self.assertNotIn("%(q)s", format_string)


if __name__ == "__main__":
    unittest.main()
