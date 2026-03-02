from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from agora.debate_executor import DebateVerdict
from scripts import run_debate


class RunDebateAuthTests(unittest.TestCase):
    def test_mock_mode_does_not_require_openrouter_key(self) -> None:
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("OPENROUTER_API_KEY", None)
        proc = subprocess.run(
            [sys.executable, str(root / "scripts" / "run_debate.py"), "--diff", "fix: noop", "--mock"],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=f"stderr={proc.stderr}")
        start = proc.stdout.find("{")
        self.assertGreaterEqual(start, 0, msg=f"stdout={proc.stdout}")
        payload = json.loads(proc.stdout[start:])
        self.assertIn(payload.get("decision"), {"APPROVE", "REQUEST_CHANGES", "SUSPEND"})

    def test_live_mode_without_key_fails_fast(self) -> None:
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("OPENROUTER_API_KEY", None)
        proc = subprocess.run(
            [sys.executable, str(root / "scripts" / "run_debate.py"), "--diff", "fix: noop"],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("openrouter auth check failed", proc.stderr)

    def test_live_mode_with_valid_key_enters_execution_stage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for d in ["config", "sessions", "governance/audits"]:
                (root / d).mkdir(parents=True, exist_ok=True)
            (root / "config" / "prompt_catalog.yaml").write_text(
                yaml.safe_dump(
                    {
                        "schema_version": "1.1",
                        "entries": [
                            {
                                "id": "p1",
                                "type": "prompt",
                                "path": "prompt_lab/a.md",
                                "status": "active",
                                "default_enabled": True,
                                "requires_authorization": None,
                            },
                            {
                                "id": "profile.debate_code_review",
                                "type": "profile",
                                "members": ["p1"],
                                "status": "active",
                                "binding_reason_template": "x",
                            },
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (root / "prompt_lab").mkdir(parents=True, exist_ok=True)
            (root / "prompt_lab" / "a.md").write_text("x", encoding="utf-8")
            (root / "config" / "llm_policy.yaml").write_text(
                yaml.safe_dump(
                    {
                        "schema_version": "1.0",
                        "provider": "openrouter",
                        "mode": "openrouter",
                        "model": "qwen/qwen3-4b:free",
                        "timeout_seconds": 30,
                        "max_retries": 1,
                        "retry_on": [500, 502, 503],
                        "fallback_on_error": False,
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            argv = ["run_debate.py", "--diff", "fix: noop"]
            fake_verdict = DebateVerdict(
                decision="APPROVE",
                session_dir=str(root / "sessions" / "debate"),
                round1_path=str(root / "sessions" / "debate" / "round_1.md"),
                round2_path=str(root / "sessions" / "debate" / "round_2.md"),
                round3_path=str(root / "sessions" / "debate" / "round_3.md"),
                recommendation="Looks good.",
            )
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-v1-aaaaaaaaaaaa"}, clear=False), patch.object(
                run_debate,
                "ROOT",
                root,
            ), patch.object(run_debate, "build_llm_client", return_value=object()), patch.object(
                run_debate.DebateExecutor,
                "run",
                return_value=fake_verdict,
            ):
                with patch.object(sys, "argv", argv):
                    rc = run_debate.main()

            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
