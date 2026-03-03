from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from agora.debate_executor import DebateCancelledError
from agora.llm_client import LlmAuthError


def execute_workflow(
    *,
    workflow_type: str,
    debate_triggered: bool,
    command_text: str,
    features_json: dict[str, Any],
    features_obj: Any,
    prompt_assets: list[Any],
    llm_policy: Any,
    llm_client: Any,
    debate_executor: Any,
    subagent_executor: Any,
    wf_dir: Path,
    cancel_check: Any = None,
    cancel_after_round: int | None = None,
    force_mock: bool = False,
) -> dict[str, Any]:
    verdict_payload: dict[str, Any] | None = None
    debate_verdict_payload: dict[str, Any] | None = None
    debate_metrics_payload: dict[str, Any] | None = None
    execution_mode: str | None = None
    cancelled_at_round: int | None = None
    subagent_llm_meta: dict[str, Any] | None = None

    if workflow_type != "code_review_workflow":
        return {
            "verdict_payload": None,
            "debate_verdict_payload": None,
            "debate_metrics_payload": None,
            "execution_mode": None,
            "workflow_status": "completed",
            "cancelled_at_round": None,
            "subagent_llm_meta": None,
        }

    if debate_triggered:
        try:
            debate_verdict = debate_executor.run(
                diff=command_text,
                routing_features=features_json,
                binding=prompt_assets,
                llm_client=llm_client,
                session_dir=wf_dir,
                use_mock=(llm_policy.mode == "mock") or force_mock,
                cancel_check=cancel_check,
                cancel_after_round=cancel_after_round,
            )
            debate_verdict_payload = asdict(debate_verdict)
            metrics_path = Path(debate_verdict.session_dir) / "debate" / "debate_metrics.json"
            if metrics_path.exists():
                try:
                    debate_metrics_payload = json.loads(metrics_path.read_text(encoding="utf-8"))
                except Exception:
                    debate_metrics_payload = None
            execution_mode = "degraded_mock" if force_mock else "debate"
            workflow_status = "completed"
        except DebateCancelledError as exc:
            execution_mode = "debate"
            workflow_status = "cancelled"
            cancelled_at_round = exc.cancelled_at_round
        except LlmAuthError as exc:
            raise HTTPException(status_code=503, detail="debate_execution_auth_failed") from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="debate_execution_failed") from exc
    else:
        try:
            if force_mock:
                verdict_payload = {
                    "decision": "REQUEST_CHANGES",
                    "hard_flag": False,
                    "summary": "REQUEST_CHANGES: degraded budget policy mock execution.",
                    "recommendation": "Retry with available budget.",
                    "claim": {
                        "agent_id": "subagent-reviewer",
                        "task_intent": "code_review",
                        "risk_level": "medium",
                        "reversibility": "partial",
                        "tool_need": False,
                        "conclusion": "Budget policy forced degraded mock execution.",
                        "evidence": ["budget_limit_exceeded"],
                        "assumptions": ["mock_fallback"],
                        "confidence": "medium",
                    },
                    "model_source": "mock:budget_policy_fallback",
                    "llm_meta": {
                        "provider": "mock",
                        "model": "mock:budget_policy_fallback",
                        "agent_id": "subagent-reviewer",
                        "round_name": "subagent",
                        "role_id": "subagent-reviewer",
                        "started_at": None,
                        "duration_ms": 0,
                        "attempts": 1,
                        "retry_count": 0,
                        "final_status_code": None,
                        "error_type": None,
                        "outcome": "ok",
                        "prompt_tokens": None,
                        "completion_tokens": None,
                        "total_tokens": None,
                        "estimated_cost_usd": None,
                        "cost_alert_exceeded": False,
                    },
                }
                execution_mode = "degraded_mock"
                workflow_status = "completed"
                subagent_llm_meta = verdict_payload.get("llm_meta")
                return {
                    "verdict_payload": verdict_payload,
                    "debate_verdict_payload": debate_verdict_payload,
                    "debate_metrics_payload": debate_metrics_payload,
                    "execution_mode": execution_mode,
                    "workflow_status": workflow_status,
                    "cancelled_at_round": cancelled_at_round,
                    "subagent_llm_meta": subagent_llm_meta,
                }
            verdict = subagent_executor.run(
                diff=command_text,
                task_features=features_obj,
                binding_assets=prompt_assets,
                llm_client=llm_client,
            )
            verdict_payload = verdict.model_dump(mode="json")
            execution_mode = "subagent"
            workflow_status = "completed"
            subagent_llm_meta = verdict_payload.get("llm_meta")
        except Exception as exc:
            raise HTTPException(status_code=503, detail="subagent_execution_failed") from exc

    return {
        "verdict_payload": verdict_payload,
        "debate_verdict_payload": debate_verdict_payload,
        "debate_metrics_payload": debate_metrics_payload,
        "execution_mode": execution_mode,
        "workflow_status": workflow_status,
        "cancelled_at_round": cancelled_at_round,
        "subagent_llm_meta": subagent_llm_meta,
    }
