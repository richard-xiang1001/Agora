from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _seed_release_root(root: Path, *, invariant_blocker: bool = False) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "governance/audits").mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(
        json.dumps(
            {
                "scripts": {
                    "desktop:pack": "PYTHONPATH=. ./.venv/bin/python scripts/desktop_pack_preflight.py",
                    "desktop:pack:raw": "electron-builder --mac zip dmg",
                    "release:reliability:ci": "PYTHONPATH=. ./.venv/bin/python scripts/run_reliability_release_gate.py --desktop-mode skip",
                },
                "build": {
                    "files": ["desktop/**/*", "package.json"],
                    "extraFiles": [{"from": "agora", "to": "backend/agora"}],
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "config/permissions_scopes.yaml").write_text("{}", encoding="utf-8")
    (root / "config/product_path_release_gate.yaml").write_text("{}", encoding="utf-8")
    (root / "config/reliability_release_gate.yaml").write_text(
        "thresholds:\n  require_product_path_release_gate_pass: false\n",
        encoding="utf-8",
    )
    (root / "governance/audits/product_path_benchmark.json").write_text("{}", encoding="utf-8")
    (root / "governance/audits/product_path_benchmark_history.jsonl").write_text("", encoding="utf-8")
    if invariant_blocker:
        wf_dir = root / "sessions" / "s1" / "workflows" / "wf-1"
        wf_dir.mkdir(parents=True)
        (wf_dir / "workflow.json").write_text(
            json.dumps(
                {
                    "workflow_id": "wf-1",
                    "status": "waiting_user",
                    "chat_result": {
                        "pending_actions": [
                            {
                                "workflow_id": "wf-1",
                                "action_id": "act-1",
                                "action": "shell_exec",
                                "approval_required": True,
                                "approval_source": "tool_permission",
                            }
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )


class ReleaseHygieneTests(unittest.TestCase):
    def test_package_scripts_bind_pack_to_preflight_and_keep_raw_pack(self) -> None:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        scripts = package.get("scripts") or {}
        self.assertIn("scripts/desktop_pack_preflight.py", scripts.get("desktop:pack", ""))
        self.assertEqual(scripts.get("desktop:pack:raw"), "electron-builder --mac zip dmg")

    def test_pack_preflight_blocks_before_raw_pack_when_gate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_release_root(root, invariant_blocker=True)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            marker = root / "raw-pack-called"
            fake_npm = fake_bin / "npm"
            fake_npm.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n", encoding="utf-8")
            fake_npm.chmod(fake_npm.stat().st_mode | stat.S_IXUSR)
            env = dict(os.environ)
            env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/desktop_pack_preflight.py"),
                    "--root",
                    str(root),
                    "--desktop-mode",
                    "skip",
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                timeout=120,
                env=env,
            )
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertFalse(marker.exists())

    def test_pack_preflight_blocks_dirty_official_pack_after_gate_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_release_root(root)
            subprocess.run(["git", "init"], cwd=str(root), check=True, capture_output=True, text=True, timeout=30)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            marker = root / "raw-pack-called"
            fake_npm = fake_bin / "npm"
            fake_npm.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n", encoding="utf-8")
            fake_npm.chmod(fake_npm.stat().st_mode | stat.S_IXUSR)
            env = dict(os.environ)
            env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/desktop_pack_preflight.py"),
                    "--root",
                    str(root),
                    "--desktop-mode",
                    "skip",
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                timeout=120,
                env=env,
            )
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertFalse(marker.exists())
            output = json.loads(proc.stdout.strip().splitlines()[-1])
            self.assertEqual(output["status"], "blocked_dirty_workspace")
            self.assertTrue(output["release_policy"]["dirty_workspace"])
            self.assertTrue(output["release_policy"]["dirty_workspace_blocked"])

    def test_pack_preflight_dry_run_generates_release_evidence_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_release_root(root)
            subprocess.run(["git", "init"], cwd=str(root), check=True, capture_output=True, text=True, timeout=30)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/desktop_pack_preflight.py"),
                    "--root",
                    str(root),
                    "--desktop-mode",
                    "skip",
                    "--dry-run",
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            manifest_path = root / "governance/audits/release_evidence_manifest.json"
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], "agora_release_evidence_manifest_v1")
            self.assertEqual(manifest["reliability_gate"]["decision"], "pass")
            self.assertIn("desktop_dogfood", manifest["artifacts"])
            self.assertTrue(manifest["checks_summary"])
            self.assertIn("git", manifest)
            self.assertIn("blocking_config", manifest)
            self.assertTrue(manifest["git"]["dirty"])
            self.assertEqual(manifest["release_policy"]["decision"], "allowed")
            self.assertFalse(manifest["release_policy"]["dirty_workspace_blocked"])

    def test_package_scripts_include_ci_reliability_wiring(self) -> None:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        scripts = package.get("scripts") or {}
        self.assertIn("--desktop-mode skip", scripts.get("release:reliability:ci", ""))
        self.assertIn("uv run", scripts.get("release:reliability:ci", ""))
        self.assertIn("--with-requirements requirements.txt", scripts.get("release:reliability:ci", ""))

    def test_pr_template_covers_release_review_boundary(self) -> None:
        template = (ROOT / ".github/pull_request_template.md").read_text(encoding="utf-8")
        self.assertIn("Review Boundary", template)
        self.assertIn("desktop:pack", template)
        self.assertIn("dirty", template.lower())
        self.assertIn("Release evidence manifest", template)
        self.assertIn("mark-legacy-safe --dry-run", template)
        self.assertIn("governance/audits/*.json", template)

    def test_ci_workflow_runs_wiring_gate_without_desktop_pack(self) -> None:
        workflow = (ROOT / ".github/workflows/reliability-ci.yml").read_text(encoding="utf-8")
        self.assertIn("npm run release:reliability:ci", workflow)
        self.assertIn("tests/test_release_hygiene.py", workflow)
        self.assertNotIn("desktop:pack", workflow)
        self.assertNotIn("--desktop-mode electron", workflow)

    def test_release_checklist_marks_raw_pack_as_non_release_path(self) -> None:
        checklist = (ROOT / "docs/macos_release_checklist.md").read_text(encoding="utf-8")
        self.assertIn("git status --short", checklist)
        self.assertIn("npm run desktop:pack", checklist)
        self.assertIn("desktop:pack:raw", checklist)
        self.assertIn("only for local packaging debugging", checklist)
        self.assertIn("release_evidence_manifest.json", checklist)
        self.assertIn("git.dirty=false", checklist)

    def test_reliability_runbook_documents_rehearsal_and_evidence_boundary(self) -> None:
        runbook = (ROOT / "docs/runbooks/reliability_release.md").read_text(encoding="utf-8")
        self.assertIn("Review Boundary", runbook)
        self.assertIn("Suggested staging commands", runbook)
        self.assertIn("Do not include `governance/audits/*.json`", runbook)
        self.assertIn("Evidence Bundle", runbook)
        self.assertIn("scripts/build_release_evidence_bundle.py", runbook)
        self.assertIn("scripts/check_review_boundary.py", runbook)
        self.assertIn("Release Rehearsal", runbook)
        self.assertIn("git status --short", runbook)
        self.assertIn("tee dist/release-evidence/rehearsal-command.log", runbook)
        self.assertIn("artifact bundle", runbook)

    def test_release_checklist_requires_evidence_bundle_after_rehearsal(self) -> None:
        checklist = (ROOT / "docs/macos_release_checklist.md").read_text(encoding="utf-8")
        self.assertIn("scripts/build_release_evidence_bundle.py", checklist)
        self.assertIn("bundle_manifest.json", checklist)
        self.assertIn("reliability_gate.decision=pass", checklist)
        self.assertIn("artifact bundle", checklist)

    def test_reliability_release_evidence_is_gitignored(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("governance/audits/reliability_release_gate.json", gitignore)
        self.assertIn("governance/audits/desktop_dogfood_gate_run_*.json", gitignore)
        self.assertIn("governance/audits/release_evidence_manifest.json", gitignore)
        self.assertIn("governance/audits/runtime_invariant_report.json", gitignore)

    def test_desktop_regression_artifact_redacts_provider_keys_at_source(self) -> None:
        script = (ROOT / "scripts/desktop_electron_live_regression.js").read_text(encoding="utf-8")
        self.assertIn("function redactSecrets", script)
        self.assertIn("function artifactDesktopConfig", script)
        self.assertIn("JSON.stringify(redactSecrets(output)", script)
        self.assertIn("[REDACTED_OPENROUTER_KEY]", script)


if __name__ == "__main__":
    unittest.main()
