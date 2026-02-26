from __future__ import annotations

import unittest

from agora.redteam import run_redteam_suite


class RedteamTests(unittest.TestCase):
    def test_redteam_suite_runs_with_thresholds(self) -> None:
        results = run_redteam_suite(
            suite_path="redteam/suite.yaml",
            thresholds_path="redteam/thresholds.yaml",
            routing_rules_path="policy/routing_rules.yaml",
            heartbeat_contract_path="config/heartbeat_contract.yaml",
        )
        self.assertGreaterEqual(len(results), 6)
        by_cat = {r.category: r for r in results}
        self.assertIn("hard_constraint", by_cat)
        self.assertIn("fault_storm", by_cat)
        self.assertTrue(by_cat["hard_constraint"].passed_threshold)
        self.assertTrue(by_cat["fault_storm"].passed_threshold)


if __name__ == "__main__":
    unittest.main()
