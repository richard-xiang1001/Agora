from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agora.doctor_migration import build_doctor_report
from agora.reliability_release_gate import evaluate_reliability_release_gate


def get_doctor_report(*, app: Any, root: Path) -> dict[str, Any]:
    return build_doctor_report(app=app, root=root, write_report=True)


def get_reliability_gate_report(*, root: Path) -> dict[str, Any]:
    report_path = root / "governance" / "audits" / "reliability_release_gate.json"
    if report_path.exists():
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return dict(payload)
        except Exception:
            pass
    return evaluate_reliability_release_gate(root=root)
