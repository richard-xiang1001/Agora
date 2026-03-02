from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class LintPromptEmbeddingLiveGateTests(unittest.TestCase):
    def test_alert_when_pass_rate_and_auth_failed_bad(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            history = Path(td) / 'history.jsonl'
            out = Path(td) / 'trend.json'
            rows = [
                {'passed': False, 'total_ms': 130000, 'auth_failed_count': 0},
                {'passed': True, 'total_ms': 110000, 'auth_failed_count': 1},
                {'passed': False, 'total_ms': 140000, 'auth_failed_count': 1},
            ]
            history.write_text('\n'.join(json.dumps(x, ensure_ascii=True) for x in rows) + '\n', encoding='utf-8')
            proc = subprocess.run(
                [
                    'python3',
                    'scripts/lint_prompt_embedding_live_gate.py',
                    '--history',
                    str(history),
                    '--out',
                    str(out),
                    '--window',
                    '7',
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            data = json.loads(out.read_text(encoding='utf-8'))
            self.assertIn('pass_rate_below_0.8', data['alerts'])
            self.assertIn('p95_total_ms_above_120000', data['alerts'])
            self.assertIn('consecutive_auth_failed', data['alerts'])


if __name__ == '__main__':
    unittest.main()
