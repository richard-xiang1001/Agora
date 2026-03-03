from __future__ import annotations

import unittest
from pathlib import Path


class DebateLayerStructureTests(unittest.TestCase):
    def test_debate_executor_is_facade_sized(self) -> None:
        path = Path("agora/debate_executor.py")
        text = path.read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 300)
        self.assertIn("from agora.debate.round_runner import", text)

    def test_debate_layer_modules_exist(self) -> None:
        for p in [
            Path("agora/debate/round_runner.py"),
            Path("agora/debate/metrics_writer.py"),
            Path("agora/debate/cancel_policy.py"),
        ]:
            self.assertTrue(p.exists(), msg=f"missing {p}")


if __name__ == "__main__":
    unittest.main()
