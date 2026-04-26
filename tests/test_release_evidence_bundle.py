from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _seed_bundle_fixture(root: Path) -> None:
    audits = root / "governance" / "audits"
    audits.mkdir(parents=True)
    artifacts = {
        "desktop_dogfood": str(audits / "desktop_dogfood_gate.json"),
        "runtime_invariants": str(audits / "runtime_invariant_report.json"),
        "capability_redteam": str(audits / "capability_redteam_report.json"),
        "product_path_release_gate": str(audits / "product_path_release_gate.json"),
        "beta_packaging_readiness": str(audits / "beta_packaging_readiness.json"),
        "missing_optional": str(audits / "missing_optional.json"),
    }
    for name, path in artifacts.items():
        if name == "missing_optional":
            continue
        Path(path).write_text(json.dumps({"artifact": name, "token": "sk-or-v1-SECRET123"}), encoding="utf-8")
    (audits / "desktop_dogfood_gate_run_1.json").write_text(json.dumps({"run": 1}), encoding="utf-8")
    (audits / "runtime_invariant_repair_ledger.jsonl").write_text('{"action":"mark"}\n', encoding="utf-8")
    gate = {
        "decision": "pass",
        "blocked": False,
        "artifacts": artifacts,
        "checks": [{"name": "desktop_dogfood_gate", "passed": True, "required": True}],
    }
    (audits / "reliability_release_gate.json").write_text(json.dumps(gate), encoding="utf-8")
    manifest = {
        "schema_version": "agora_release_evidence_manifest_v1",
        "git": {"head": "abc", "dirty": False},
        "reliability_gate": {"decision": "pass", "blocked": False},
        "artifacts": artifacts,
    }
    (audits / "release_evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class ReleaseEvidenceBundleTests(unittest.TestCase):
    def test_bundle_copies_artifacts_and_records_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_bundle_fixture(root)
            out = root / "dist" / "release-evidence" / "fixture"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/build_release_evidence_bundle.py"),
                    "--root",
                    str(root),
                    "--out-dir",
                    str(out),
                ],
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            bundle_manifest = json.loads((out / "bundle_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(bundle_manifest["schema_version"], "agora_release_evidence_bundle_v1")
            copied_names = {Path(item["path"]).name for item in bundle_manifest["copied_files"]}
            self.assertIn("release_evidence_manifest.json", copied_names)
            self.assertIn("reliability_release_gate.json", copied_names)
            self.assertIn("desktop_dogfood_gate_run_1.json", copied_names)
            self.assertIn("runtime_invariant_repair_ledger.jsonl", copied_names)
            missing_labels = {item["label"] for item in bundle_manifest["missing_artifacts"]}
            self.assertIn("missing_optional", missing_labels)
            self.assertTrue((out / "command_log_missing.txt").exists())

    def test_bundle_zip_contains_manifest_and_key_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_bundle_fixture(root)
            out = root / "dist" / "release-evidence" / "fixture"
            command_log = root / "release.log"
            command_log.write_text("npm run desktop:pack -- --dry-run\nsk-or-v1-SECRET123\n", encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/build_release_evidence_bundle.py"),
                    "--root",
                    str(root),
                    "--out-dir",
                    str(out),
                    "--command-log",
                    str(command_log),
                    "--zip",
                ],
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            zip_path = out.with_suffix(".zip")
            self.assertTrue(zip_path.exists())
            with zipfile.ZipFile(zip_path) as zf:
                names = set(zf.namelist())
                command_log_text = zf.read("fixture/command_log.txt").decode("utf-8")
                artifact_text = zf.read("fixture/artifacts/reliability_release_gate.json").decode("utf-8")
            self.assertIn("fixture/bundle_manifest.json", names)
            self.assertIn("fixture/command_log.txt", names)
            self.assertIn("fixture/artifacts/reliability_release_gate.json", names)
            self.assertIn("[REDACTED_OPENROUTER_KEY]", command_log_text)
            self.assertNotIn("sk-or-v1-SECRET123", command_log_text)
            self.assertNotIn("sk-or-v1-SECRET123", artifact_text)

    def test_bundle_dry_run_does_not_create_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_bundle_fixture(root)
            out = root / "dist" / "release-evidence" / "fixture"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/build_release_evidence_bundle.py"),
                    "--root",
                    str(root),
                    "--out-dir",
                    str(out),
                    "--dry-run",
                ],
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
