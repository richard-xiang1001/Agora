from __future__ import annotations

import unittest

from agora.fault_storm import run_fault_storm_drill


class FaultStormTests(unittest.TestCase):
    def test_fault_storm_drill_passes(self) -> None:
        result = run_fault_storm_drill()
        self.assertTrue(result.timeout_failover_ok)
        self.assertTrue(result.wal_readonly_ok)
        self.assertTrue(result.overall_pass)


if __name__ == "__main__":
    unittest.main()
