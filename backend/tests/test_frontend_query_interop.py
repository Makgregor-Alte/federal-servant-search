"""Cross-check web query strings against the Flask search parameter parser."""
import json
from pathlib import Path
from urllib.parse import parse_qs
import shutil
import subprocess
import unittest

from app.search import parse_filters

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("node"), "Node.js is needed for cross-language contract tests")
class FrontendQueryInteropTests(unittest.TestCase):
    def test_react_query_parameters_are_accepted_by_flask(self):
        script = """
            import { buildQuery } from './frontend/src/api/query.js';
            const base = { name: '', name_mode: 'similar', position: '', agency: '', uf: '', page_size: '20' };
            const scenarios = [
              [{ name: 'Maria Silva', name_mode: 'exact' }, 1],
              [{ name: 'Mariana', name_mode: 'similar' }, 1],
              [{ name: '%João%Silva%', position: 'Técnico', agency: 'Universidade', uf: 'RS', page_size: '50' }, 3],
              [{ name: 'NOME SOBRENOME%' }, 1],
              [{ name: 'NOME%SOBRENOME' }, 1],
              [{ position: 'Analista', uf: 'SP' }, 2],
            ];
            console.log(JSON.stringify(scenarios.map(([parts, page]) => buildQuery({ ...base, ...parts }, page))));
        """
        execution = subprocess.run(
            ["node", "--input-type=module", "-e", script], cwd=ROOT,
            capture_output=True, text=True, timeout=10, check=True,
        )
        strings = json.loads(execution.stdout)
        self.assertEqual(len(strings), 6)
        parsed = []
        for query in strings:
            values = parse_qs(query, keep_blank_values=True)
            self.assertTrue(all(len(options) == 1 for options in values.values()))
            parsed.append(parse_filters({key: options[0] for key, options in values.items()}))
        self.assertEqual(parsed[0].name_mode, 'exact')
        self.assertEqual(parsed[1].name_mode, 'similar')
        self.assertEqual(parsed[2].name_mode, 'pattern')
        self.assertEqual(parsed[2].page, 3)
        self.assertEqual(parsed[2].uf, 'RS')
        self.assertEqual(parsed[3].name_mode, 'pattern')
        self.assertEqual(parsed[4].name_mode, 'pattern')
        self.assertEqual(parsed[5].position, 'Analista')


if __name__ == "__main__":
    unittest.main()
