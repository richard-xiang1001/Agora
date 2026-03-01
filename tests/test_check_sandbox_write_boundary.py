from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_sandbox_write_boundary import check_boundary


class CheckSandboxWriteBoundaryTests(unittest.TestCase):
    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def test_pass_when_only_allowed_paths_modified(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sandbox_root = root / "sandbox"
            sandbox_root.mkdir(parents=True, exist_ok=True)

            t0 = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
            wf = "wf-ok"
            d = sandbox_root / wf
            d.mkdir(parents=True, exist_ok=True)
            (d / "out.txt").write_text("ok\n", encoding="utf-8")

            summary = root / "summary.json"
            registry = root / "registry.json"
            self._write_json(
                summary,
                {
                    "t0": t0.isoformat(),
                    "executed_workflow_ids": [wf],
                },
            )
            self._write_json(registry, {"workflow_ids": [wf]})
            ok, violations = check_boundary(
                summary_path=summary,
                registry_path=registry,
                sandbox_root=sandbox_root,
            )
            self.assertTrue(ok)
            self.assertEqual(violations, [])

    def test_fail_on_out_of_boundary_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sandbox_root = root / "sandbox"
            sandbox_root.mkdir(parents=True, exist_ok=True)

            t0 = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
            wf = "wf-a"
            (sandbox_root / wf).mkdir(parents=True, exist_ok=True)
            (sandbox_root / wf / "ok.txt").write_text("ok\n", encoding="utf-8")
            rogue = sandbox_root / "rogue.txt"
            rogue.write_text("bad\n", encoding="utf-8")

            summary = root / "summary.json"
            registry = root / "registry.json"
            self._write_json(summary, {"t0": t0.isoformat(), "executed_workflow_ids": [wf]})
            self._write_json(registry, {"workflow_ids": [wf]})
            ok, violations = check_boundary(
                summary_path=summary,
                registry_path=registry,
                sandbox_root=sandbox_root,
            )
            self.assertFalse(ok)
            self.assertTrue(any("rogue.txt" in v for v in violations))

    def test_ignore_when_no_intersection_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sandbox_root = root / "sandbox"
            sandbox_root.mkdir(parents=True, exist_ok=True)
            rogue = sandbox_root / "rogue.txt"
            rogue.write_text("bad\n", encoding="utf-8")

            t0 = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
            summary = root / "summary.json"
            registry = root / "registry.json"
            self._write_json(summary, {"t0": t0.isoformat(), "executed_workflow_ids": ["wf-x"]})
            self._write_json(registry, {"workflow_ids": ["wf-y"]})
            ok, violations = check_boundary(
                summary_path=summary,
                registry_path=registry,
                sandbox_root=sandbox_root,
            )
            self.assertTrue(ok)
            self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
