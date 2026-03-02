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

from agora.debate_executor import DebateExecutor, DebateExecutorError, DebateRoundTimeoutError
from agora.llm_client import LlmAuthError, build_llm_client, load_llm_policy, validate_openrouter_auth
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
    if not args.mock:
        if llm_policy.mode != "openrouter":
            print(
                f"[FAIL] run_debate live mode requires llm_policy.mode=openrouter, got {llm_policy.mode}",
                file=sys.stderr,
            )
            return 2
        try:
            auth_meta = validate_openrouter_auth(llm_policy)
        except LlmAuthError as exc:
            print(f"[FAIL] openrouter auth check failed: {exc}", file=sys.stderr)
            return 2
        print(
            json.dumps(
                {
                    "auth_provider": auth_meta.get("provider"),
                    "auth_model": auth_meta.get("model"),
                    "auth_key_fingerprint": auth_meta.get("key_fingerprint"),
                },
                ensure_ascii=True,
            ),
            file=sys.stderr,
        )
    llm_client = build_llm_client(llm_policy, root_dir=root, repo_root=root)

    routing_features = {
        "task_intent": "code_review",
        "risk_level": "medium",
        "reversibility": "partial",
        "requires_tools": False,
        "confidence": 0.9,
    }

    def _progress(round_name: str, phase: str, elapsed: float | None) -> None:
        if phase == "start":
            if round_name == "round1":
                print("[round1] starting 6 roles...", flush=True)
            elif round_name == "round2":
                print("[round2] starting cross-critique...", flush=True)
            elif round_name == "round3":
                print("[round3] starting convergence...", flush=True)
            return
        if phase == "done":
            secs = 0.0 if elapsed is None else elapsed
            print(f"[{round_name}] done ({secs:.1f}s)", flush=True)

    try:
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
            progress_cb=_progress,
        )
    except DebateRoundTimeoutError as exc:
        print(f"[FAIL] debate round timeout: {exc}", file=sys.stderr)
        return 3
    except DebateExecutorError as exc:
        print(f"[FAIL] debate execution error: {exc}", file=sys.stderr)
        return 1

    print(f"[done] decision={verdict.decision}", flush=True)
    print(json.dumps(asdict(verdict), ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
