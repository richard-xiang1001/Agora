from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from agora.debate_engine import DebateEngine


class DebateEngineTests(unittest.TestCase):
    def test_three_round_file_workflow(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as td:
                session = Path(td)
                engine = DebateEngine()

                r1 = await engine.round1_parallel_claims(
                    session,
                    {
                        "agent_a": "A claims SQL injection risk",
                        "agent_b": "B claims safe with sanitization",
                    },
                )
                self.assertTrue(r1.exists())
                self.assertTrue((session / "claims" / "agent_a.md").exists())
                self.assertTrue((session / "claims" / "agent_b.md").exists())

                r2 = await engine.round2_cross_critique(
                    session,
                    {
                        "agent_a": "B assumes sanitization without evidence.",
                        "agent_b": "A lacks runtime exploit proof.",
                    },
                )
                self.assertTrue(r2.exists())
                self.assertIn("Cross Critiques", r2.read_text(encoding="utf-8"))

                r3 = await engine.round3_converge(
                    session,
                    mode="majority_with_minority",
                    summary="Majority says high-risk and requires patch.",
                    minority_view="Minority requests verification in sandbox.",
                )
                text = r3.read_text(encoding="utf-8")
                self.assertIn("mode: majority_with_minority", text)
                self.assertIn("Minority View", text)

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
