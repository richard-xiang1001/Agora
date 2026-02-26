from __future__ import annotations

import unittest

from agora.fallback import FallbackManager


class FallbackManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = FallbackManager(
            chains={"coding": ["claude-3.7", "o4-mini", "gpt-4o"]},
            base_backoff_seconds=2,
        )

    def test_select_primary_by_default(self) -> None:
        self.assertEqual(self.manager.select_model("coding"), "claude-3.7")

    def test_switch_to_fallback_on_failure(self) -> None:
        event = self.manager.record_failure("coding", "timeout")
        self.assertEqual(event.primary_model, "claude-3.7")
        self.assertEqual(event.switchover_model, "o4-mini")
        self.assertEqual(event.recovery_status, "pending")
        self.assertEqual(self.manager.select_model("coding"), "o4-mini")

    def test_recover_to_primary(self) -> None:
        self.manager.record_failure("coding", "timeout")
        self.manager.record_recovered("coding")
        self.assertEqual(self.manager.select_model("coding"), "claude-3.7")


if __name__ == "__main__":
    unittest.main()
