from __future__ import annotations

import tempfile
import unittest
import os
from pathlib import Path

from fastapi.testclient import TestClient

from agora.api import create_app


class ReliabilityApiTests(unittest.TestCase):
    def test_runtime_invariants_and_doctor_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "config").mkdir(parents=True, exist_ok=True)
            (root / "config/permissions_scopes.yaml").write_text("{}", encoding="utf-8")
            os.environ.setdefault("OPENROUTER_API_KEY", "sk-or-v1-test")
            client = TestClient(create_app(root))
            try:
                invariants = client.get("/v1/runtime/invariants")
                self.assertEqual(invariants.status_code, 200)
                self.assertIn("summary", invariants.json())
                repaired = client.post("/v1/runtime/invariants/repair")
                self.assertEqual(repaired.status_code, 200)
                status = client.get("/v1/runtime/status")
                self.assertEqual(status.status_code, 200)
                self.assertIn("runtime_invariants", status.json())
                doctor = client.get("/v1/ui/doctor")
                self.assertEqual(doctor.status_code, 200)
                self.assertIn("schema_migrations", doctor.json())
                gate = client.get("/v1/ui/reliability-gate")
                self.assertEqual(gate.status_code, 200)
                self.assertIn("checks", gate.json())
            finally:
                client.close()


if __name__ == "__main__":
    unittest.main()
