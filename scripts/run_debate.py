#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agora.debate_executor import DebateExecutor
from agora.llm_client import build_llm_client, load_llm_policy
from agora.prompt_registry import load_catalog


def main() -> int:
    parser = argparse.ArgumentParser(description="Run DebateExecutor 3-round flow")
    parser.add_argument("--diff", required=True, help="Unified diff text")
    parser.add_argument("--mock", action="store_true", help="Use fixtures instead of live llm calls")
    parser.add_argument("--session-dir", default=None, help="Optional output session directory")
    args = parser.parse_args()

    root = ROOT
    registry = load_catalog(
        root / "config" / "prompt_catalog.yaml",
        root_dir=root,
        audit_dir=root / "governance" / "audits",
    )
    binding = registry.resolve_profile("profile.debate_code_review")

    llm_policy = load_llm_policy(root / "config" / "llm_policy.yaml")
    llm_client = build_llm_client(llm_policy, root_dir=root, repo_root=root)

    routing_features = {
        "task_intent": "code_review",
        "risk_level": "medium",
        "reversibility": "partial",
        "requires_tools": False,
        "confidence": 0.9,
    }

    verdict = DebateExecutor(
        prompt_root_dir=root,
        fixture_root_dir=root / "tests" / "fixtures" / "mock_llm_responses" / "debate",
        llm_policy=llm_policy,
    ).run(
        diff=args.diff,
        routing_features=routing_features,
        binding=binding,
        llm_client=llm_client,
        session_dir=args.session_dir,
        use_mock=args.mock,
    )

    print(json.dumps(asdict(verdict), ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
