from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


class PromptEmbeddingLiveGateScriptTests(unittest.TestCase):
    def test_live_gate_dry_run_generates_report_and_history(self) -> None:
        report = Path('governance/audits/prompt_embedding_live_gate.json')
        history = Path('governance/audits/prompt_embedding_live_gate_history.jsonl')
        before = 0
        if history.exists():
            before = len([x for x in history.read_text(encoding='utf-8').splitlines() if x.strip()])

        proc = subprocess.run(
            ['bash', 'scripts/run_prompt_embedding_live_gate.sh', '--dry-run'],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + '\n' + proc.stderr)
        self.assertTrue(report.exists())
        data = json.loads(report.read_text(encoding='utf-8'))
        self.assertIn('generated_at', data)
        self.assertIn('checks', data)
        self.assertIn('total_ms', data)
        self.assertTrue(data['passed'])

        self.assertTrue(history.exists())
        after = len([x for x in history.read_text(encoding='utf-8').splitlines() if x.strip()])
        self.assertGreaterEqual(after, before + 1)


if __name__ == '__main__':
    unittest.main()
