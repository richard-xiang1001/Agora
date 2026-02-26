#!/usr/bin/env python3
import argparse
import json
import os
import pathlib
import re
import textwrap
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    agent_id: str
    task_intent: Literal["code_review", "research", "planning", "general", "unknown"]
    risk_level: Literal["low", "medium", "high"]
    reversibility: Literal["reversible", "partial", "irreversible"]
    tool_need: bool
    conclusion: str
    evidence: list[str]
    assumptions: list[str]
    confidence: Literal["low", "medium", "high"]


class FeatureTag(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    task_intent: Literal["code_review", "research", "planning", "general", "unknown"]
    risk_level: Literal["low", "medium", "high"]
    reversibility: Literal["reversible", "partial", "irreversible"]
    tool_need: bool


def _to_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return []
        # Split multiline bullets when available; otherwise keep single item.
        parts = [p.strip("- ").strip() for p in txt.splitlines() if p.strip()]
        return parts if parts else [txt]
    if value is None:
        return []
    return [str(value)]


def normalize_claim_payload(raw: dict[str, Any]) -> dict[str, Any]:
    out = dict(raw)
    out["conclusion"] = str(out.get("conclusion", "No conclusion provided by model.")).strip()
    out["evidence"] = _to_string_list(out.get("evidence")) or ["No evidence provided."]
    out["assumptions"] = _to_string_list(out.get("assumptions")) or ["No assumptions provided."]

    conf = str(out.get("confidence", "medium")).strip().lower()
    if conf not in {"low", "medium", "high"}:
        conf = "medium"
    out["confidence"] = conf

    tool_need = out.get("tool_need", False)
    if isinstance(tool_need, str):
        out["tool_need"] = tool_need.strip().lower() in {"1", "true", "yes", "y"}
    else:
        out["tool_need"] = bool(tool_need)
    return out


def feature_validation_gate(raw: dict[str, Any]) -> tuple[dict[str, Any], str]:
    try:
        tags = FeatureTag(
            task_intent=raw.get("task_intent"),
            risk_level=raw.get("risk_level"),
            reversibility=raw.get("reversibility"),
            tool_need=raw.get("tool_need"),
        )
        return tags.model_dump(), "pass"
    except ValidationError:
        return {
            "task_intent": "unknown",
            "risk_level": "medium",
            "reversibility": "reversible",
            "tool_need": False,
        }, "degraded_to_unknown"


def build_mock_claim(agent_id: str, code: str) -> dict[str, Any]:
    has_concat_sql = "+ username" in code or '" + ' in code
    conclusion = (
        "Potential SQL injection risk due to string concatenation in query construction."
        if has_concat_sql
        else "No obvious SQL injection pattern found in this snippet."
    )
    return {
        "agent_id": agent_id,
        "task_intent": "code_review",
        "risk_level": "high" if has_concat_sql else "low",
        "reversibility": "reversible",
        "tool_need": False,
        "conclusion": conclusion,
        "evidence": [
            "Dynamic SQL query constructed via string concatenation.",
            "User input appears directly in query string.",
        ]
        if has_concat_sql
        else ["No direct string-concatenated SQL observed."],
        "assumptions": [
            "Database layer does not auto-parameterize raw SQL strings.",
            "User input can contain malicious payload characters.",
        ],
        "confidence": "high" if has_concat_sql else "medium",
    }


def _claim_prompt(code: str, agent_id: str) -> str:
    return textwrap.dedent(
        f"""
        You are an expert code reviewer.
        Return ONLY a JSON object with exactly these keys:
        agent_id, task_intent, risk_level, reversibility, tool_need, conclusion, evidence, assumptions, confidence

        Allowed enums:
        - task_intent: code_review|research|planning|general|unknown
        - risk_level: low|medium|high
        - reversibility: reversible|partial|irreversible
        - confidence: low|medium|high

        Use agent_id="{agent_id}".
        Analyze this code:
        ```python
        {code}
        ```
        """
    ).strip()


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def call_openai_claim(code: str) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "You output strict JSON only for schema-constrained code review claims.",
            },
            {"role": "user", "content": _claim_prompt(code, "openai-reviewer")},
        ],
    )
    content = response.choices[0].message.content or "{}"
    return _extract_json_object(content)


def call_openrouter_claim(code: str, model: str, agent_id: str) -> dict[str, Any]:
    from openai import OpenAI

    headers: dict[str, str] = {}
    referer = os.getenv("OPENROUTER_SITE_URL")
    app_name = os.getenv("OPENROUTER_APP_NAME")
    if referer:
        headers["HTTP-Referer"] = referer
    if app_name:
        headers["X-Title"] = app_name

    client = OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        default_headers=headers or None,
    )
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "You output strict JSON only for schema-constrained code review claims.",
            },
            {"role": "user", "content": _claim_prompt(code, agent_id)},
        ],
    )
    content = response.choices[0].message.content or "{}"
    claim = _extract_json_object(content)
    claim["agent_id"] = agent_id
    return claim


def call_openrouter_claim_with_fallback(
    code: str, preferred_models: list[str], agent_id: str, exclude_models: set[str] | None = None
) -> tuple[dict[str, Any], str]:
    exclude_models = exclude_models or set()
    errors: list[str] = []
    # First pass: avoid excluded models to maximize reviewer diversity.
    for model in preferred_models:
        if model in exclude_models:
            continue
        try:
            claim = call_openrouter_claim(code, model, agent_id)
            claim["agent_id"] = f"{agent_id}:{model}"
            return claim, model
        except Exception as exc:
            errors.append(f"{model}: {exc.__class__.__name__}")

    # Second pass: allow excluded models if needed to keep workflow live.
    for model in preferred_models:
        try:
            claim = call_openrouter_claim(code, model, agent_id)
            claim["agent_id"] = f"{agent_id}:{model}"
            return claim, model
        except Exception as exc:
            errors.append(f"{model}: {exc.__class__.__name__}")

    raise RuntimeError(f"all OpenRouter model attempts failed for {agent_id}: {errors}")


def _assert_free_models(models: list[str]) -> None:
    non_free = [m for m in models if not m.endswith(":free")]
    if non_free:
        raise RuntimeError(f"free-only policy violation, non-free models found: {non_free}")


def call_anthropic_claim(code: str) -> dict[str, Any]:
    from anthropic import Anthropic

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
    response = client.messages.create(
        model=model,
        max_tokens=700,
        temperature=0,
        system="Output strict JSON only. No prose.",
        messages=[{"role": "user", "content": _claim_prompt(code, "anthropic-reviewer")}],
    )
    text_blocks = [b.text for b in response.content if getattr(b, "type", "") == "text"]
    content = "\n".join(text_blocks) if text_blocks else "{}"
    return _extract_json_object(content)


def maybe_live_claims(mode: str, code: str, free_only: bool = True) -> tuple[list[dict[str, Any]], str]:
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")

    if mode == "live" and (not openrouter_key and not (openai_key and anthropic_key)):
        raise RuntimeError(
            "live mode requires OPENROUTER_API_KEY or both OPENAI_API_KEY and ANTHROPIC_API_KEY"
        )

    if openrouter_key:
        model_a = os.getenv("OPENROUTER_MODEL_A", "qwen/qwen3-4b:free")
        model_b = os.getenv("OPENROUTER_MODEL_B", "meta-llama/llama-3.3-70b-instruct:free")
        extra_fallback = [
            m.strip()
            for m in os.getenv("OPENROUTER_FALLBACK_MODELS", "").split(",")
            if m.strip()
        ]
        if not extra_fallback:
            extra_fallback = [
                "arcee-ai/trinity-large-preview:free",
                "liquid/lfm-2.5-1.2b-thinking:free",
                "liquid/lfm-2.5-1.2b-instruct:free",
            ]
        chain_a = [model_a, model_b, *extra_fallback]
        chain_b = [model_b, model_a, *extra_fallback]
        if free_only:
            _assert_free_models(chain_a)
            _assert_free_models(chain_b)
        try:
            claim_a, used_a = call_openrouter_claim_with_fallback(
                code, chain_a, "openrouter-reviewer-a"
            )
            claim_b, _ = call_openrouter_claim_with_fallback(
                code, chain_b, "openrouter-reviewer-b", exclude_models={used_a}
            )
            claims = [
                claim_a,
                claim_b,
            ]
            return claims, "live_openrouter"
        except Exception:
            if mode == "live":
                raise

    if openai_key and anthropic_key:
        if free_only:
            raise RuntimeError(
                "free-only policy enabled: paid OpenAI/Anthropic direct route is disabled for tests"
            )
        try:
            claims = [call_openai_claim(code), call_anthropic_claim(code)]
            return claims, "live_openai_anthropic"
        except Exception:
            if mode == "live":
                raise

    claims = [
        build_mock_claim("gpt-4o-reviewer", code),
        build_mock_claim("claude-3-7-reviewer", code),
    ]
    return claims, "mock"


def merge_claims(valid_claims: list[Claim]) -> str:
    high_risk = any(c.risk_level == "high" for c in valid_claims)
    findings = []
    for claim in valid_claims:
        findings.append(f"- {claim.agent_id}: {claim.conclusion} (confidence={claim.confidence})")

    verdict = (
        "Consensus: high-risk code review finding requires remediation plan."
        if high_risk
        else "Consensus: no high-risk issue detected in this sample."
    )

    return "\n".join([verdict, "", "Findings:", *findings])


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MVW-A read-only code review flow.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--mode", choices=["auto", "live", "mock"], default="auto")
    parser.add_argument(
        "--allow-paid-models",
        action="store_true",
        help="Disable free-only guard for live calls (not recommended for test stage).",
    )
    parser.add_argument(
        "--lock-intent",
        choices=["code_review", "research", "planning", "general", "unknown"],
        default="code_review",
        help="Force task_intent for MVW-A to prevent fallback-model intent drift.",
    )
    parser.add_argument(
        "--code-path",
        default="sessions/mvw_a/sample_code.py",
        help="Path to input code sample",
    )
    args = parser.parse_args()

    code_path = pathlib.Path(args.code_path)
    code = code_path.read_text(encoding="utf-8")
    free_only = not args.allow_paid_models

    if args.mode == "mock":
        raw_claims, source_mode = [
            build_mock_claim("gpt-4o-reviewer", code),
            build_mock_claim("claude-3-7-reviewer", code),
        ], "mock"
    else:
        raw_claims, source_mode = maybe_live_claims(args.mode, code, free_only=free_only)

    validated_claims: list[Claim] = []
    gate_results: list[dict[str, Any]] = []

    for raw in raw_claims:
        normalized = normalize_claim_payload(raw)
        gated, gate_state = feature_validation_gate(normalized)
        merged = dict(normalized)
        merged.update(gated)
        lock_applied = False
        if merged.get("task_intent") != args.lock_intent:
            merged["task_intent"] = args.lock_intent
            lock_applied = True
        claim = Claim(**merged)
        validated_claims.append(claim)
        gate_results.append(
            {
                "agent_id": claim.agent_id,
                "gate_state": gate_state,
                "intent_lock": args.lock_intent,
                "intent_lock_applied": lock_applied,
                "tags": {
                    **gated,
                    "task_intent": claim.task_intent,
                },
            }
        )

    consensus = merge_claims(validated_claims)

    run_dir = pathlib.Path("sessions/mvw_a/runs") / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "run_id": args.run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": source_mode,
        "free_only": free_only,
        "input_code_path": str(code_path),
        "claims": [c.model_dump() for c in validated_claims],
        "feature_gate": gate_results,
        "consensus": consensus,
    }

    (run_dir / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    report = textwrap.dedent(
        f"""
        # MVW-A Run {args.run_id}

        - Mode: `{source_mode}`
        - Input: `{code_path}`

        ## Consensus
        {consensus}

        ## Feature Validation Gate
        {json.dumps(gate_results, ensure_ascii=True, indent=2)}
        """
    ).strip() + "\n"

    (run_dir / "report.md").write_text(report, encoding="utf-8")
    print(f"[PASS] MVW-A run complete: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
