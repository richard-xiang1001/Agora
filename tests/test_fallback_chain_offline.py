from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.openrouter_healthcheck import check_health


class FallbackChainOfflineTests(unittest.TestCase):
    def test_mock_mode_reports_healthy_without_dns(self) -> None:
        ok, msg = check_health(mode="mock", host="openrouter.ai", model="qwen/qwen3-4b:free")
        self.assertTrue(ok)
        self.assertEqual(msg, "mock_mode_healthy")

    def test_skip_mode_bypasses_network(self) -> None:
        ok, msg = check_health(mode="skip", host="openrouter.ai", model="qwen/qwen3-4b:free")
        self.assertTrue(ok)
        self.assertEqual(msg, "skip_mode")

    @patch("scripts.openrouter_healthcheck._check_dns", return_value=(False, "dns_error"))
    def test_live_mode_dns_failure(self, _mock_dns: unittest.mock.Mock) -> None:
        ok, msg = check_health(mode="live", host="openrouter.ai", model="qwen/qwen3-4b:free")
        self.assertFalse(ok)
        self.assertEqual(msg, "dns_error")

    @patch("scripts.openrouter_healthcheck._check_dns", return_value=(True, "dns_ok"))
    @patch("scripts.openrouter_healthcheck._check_openrouter_live", return_value=(False, "live_error"))
    def test_live_mode_fallback_error_propagates(
        self,
        _mock_live: unittest.mock.Mock,
        _mock_dns: unittest.mock.Mock,
    ) -> None:
        ok, msg = check_health(mode="live", host="openrouter.ai", model="qwen/qwen3-4b:free")
        self.assertFalse(ok)
        self.assertEqual(msg, "live_error")


if __name__ == "__main__":
    unittest.main()
