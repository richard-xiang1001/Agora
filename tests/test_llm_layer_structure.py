from __future__ import annotations

import unittest
from pathlib import Path


class LlmLayerStructureTests(unittest.TestCase):
    def test_llm_client_is_facade_sized(self) -> None:
        path = Path("agora/llm_client.py")
        text = path.read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 260)
        self.assertIn("from agora.llm import", text)

    def test_llm_layer_modules_exist(self) -> None:
        for p in [
            Path("agora/llm/policy_loader.py"),
            Path("agora/llm/provider_openrouter.py"),
            Path("agora/llm/retry_backoff.py"),
            Path("agora/llm/costing.py"),
        ]:
            self.assertTrue(p.exists(), msg=f"missing {p}")


if __name__ == "__main__":
    unittest.main()
