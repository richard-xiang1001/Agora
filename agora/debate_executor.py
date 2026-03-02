from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from pathlib import Path
from typing import Any, Callable, Literal, TypeVar

from agora.debate_engine import DebateEngine, Round3Mode
from agora.llm_client import LLMClient, LlmAuthError, LlmPolicy
from agora.prompt_types import PromptAsset

ROUND1_ROLE_IDS = [
    "security_reviewer",
    "architecture_reviewer",
    "performance_reviewer",
    "style_reviewer",
    "test_reviewer",
    "general_reviewer",
]


class DebateExecutorError(RuntimeError):
    pass


class DebateRoundTimeoutError(DebateExecutorError):
    pass


class DebateCancelledError(DebateExecutorError):
    def __init__(self, message: str, *, cancelled_at_round: int | None = None) -> None:
        super().__init__(message)
        self.cancelled_at_round = cancelled_at_round


VERDICT_RE = re.compile(r"VERDICT:\s*(APPROVE|REQUEST_CHANGES|SUSPEND)", re.IGNORECASE)
_T = TypeVar("_T")


@dataclass(frozen=True)
class DebateVerdict:
    decision: Literal["APPROVE", "REQUEST_CHANGES", "SUSPEND"]
    session_dir: str
    round1_path: str
    round2_path: str
    round3_path: str
    recommendation: str | None


class DebateExecutor:
    def __init__(
        self,
        *,
        prompt_root_dir: str | Path = ".",
        fixture_root_dir: str | Path = "tests/fixtures/mock_llm_responses/debate",
        llm_policy: LlmPolicy | None = None,
    ) -> None:
        self.prompt_root_dir = Path(prompt_root_dir)
        self.fixture_root_dir = Path(fixture_root_dir)
        self.llm_policy = llm_policy
        self._engine = DebateEngine()

    @staticmethod
    def _require_prompt(binding: list[PromptAsset], prompt_id: str) -> str:
        for asset in binding:
            if asset.id == prompt_id:
                return asset.text
        raise DebateExecutorError(f"binding missing required prompt: {prompt_id}")

    def _build_role_system_prompt(self, binding: list[PromptAsset], role_id: str) -> str:
        base = self._require_prompt(binding, "debate.base")
        role = self._require_prompt(binding, f"debate.role.{role_id}")
        return f"{base.strip()}\n\n{role.strip()}"

    def _build_orchestrator_system_prompt(self, binding: list[PromptAsset]) -> str:
        return self._require_prompt(binding, "orchestrator.debate").strip()

    def _max_parallel_roles(self) -> int:
        if self.llm_policy is None:
            return 3
        return min(6, max(1, int(self.llm_policy.debate.max_parallel_roles)))

    def _round2_claim_char_limit(self) -> int:
        if self.llm_policy is None:
            return 400
        return int(self.llm_policy.debate.round2_claim_char_limit)

    def _round2_payload_char_limit(self) -> int:
        if self.llm_policy is None:
            return 3500
        return int(self.llm_policy.debate.round2_payload_char_limit)

    def _round3_payload_char_limit(self) -> int:
        if self.llm_policy is None:
            return 5000
        return int(self.llm_policy.debate.round3_payload_char_limit)

    @staticmethod
    def _emit_warning_event(session_dir: Path, event_type: str, payload: dict[str, Any]) -> None:
        debate_dir = session_dir / "debate"
        debate_dir.mkdir(parents=True, exist_ok=True)
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": "WARNING",
            "event_type": event_type,
            "payload": payload,
        }
        with (debate_dir / "debate_events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=True) + "\n")

    def _load_fixture(self, name: str) -> str:
        path = self.fixture_root_dir / name
        if not path.exists():
            raise DebateExecutorError(f"missing debate mock fixture: {path}")
        return path.read_text(encoding="utf-8").strip()

    @staticmethod
    def _extract_round1_verdict(text: str) -> Literal["APPROVE", "REQUEST_CHANGES", "SUSPEND"]:
        match = VERDICT_RE.search(str(text))
        if not match:
            return "REQUEST_CHANGES"
        value = match.group(1).upper()
        if value == "SUSPEND":
            return "SUSPEND"
        if value == "APPROVE":
            return "APPROVE"
        return "REQUEST_CHANGES"

    def _truncate(self, text: str, limit: int) -> str:
        value = str(text)
        if len(value) <= limit:
            return value
        return value[: max(0, limit - 14)] + "...[TRUNCATED]"

    def _short_claim_for_round2(self, claim_text: str) -> str:
        text = str(claim_text).strip()
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        verdict_match = VERDICT_RE.search(text)
        verdict_line = (
            f"VERDICT: {verdict_match.group(1).upper()}"
            if verdict_match
            else "VERDICT: REQUEST_CHANGES"
        )
        first = ""
        for ln in lines:
            if not ln.upper().startswith("VERDICT:"):
                first = ln
                break
        if not first:
            first = "No claim text."
        return self._truncate(f"{first}\n{verdict_line}", self._round2_claim_char_limit())

    def _is_role_retryable(self, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code in {429, 500, 502, 503, 504}:
            return True
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            return True
        return False

    def _degraded_role_output(self, role_id: str, exc: Exception) -> str:
        return f"LLM error for {role_id}: {exc.__class__.__name__}\nVERDICT: REQUEST_CHANGES"

    def _degraded_meta(self, *, role_id: str, round_name: str, started_at: str, duration_ms: int, exc: Exception) -> dict[str, Any]:
        status_code = getattr(exc, "status_code", None)
        timeout_like = isinstance(exc, (TimeoutError, asyncio.TimeoutError))
        return {
            "provider": "openrouter" if self.llm_policy and self.llm_policy.mode == "openrouter" else "unknown",
            "model": self.llm_policy.model if self.llm_policy else "unknown",
            "agent_id": role_id,
            "round_name": round_name,
            "role_id": role_id,
            "started_at": started_at,
            "duration_ms": duration_ms,
            "attempts": 1,
            "retry_count": 0,
            "final_status_code": status_code if isinstance(status_code, int) else None,
            "error_type": exc.__class__.__name__,
            "outcome": "timeout" if timeout_like else "retry_exhausted",
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "estimated_cost_usd": None,
        }

    @staticmethod
    def _claim_to_verdict_keyword(claim: dict[str, Any]) -> str:
        risk = str(claim.get("risk_level", "medium")).lower().strip()
        rev = str(claim.get("reversibility", "reversible")).lower().strip()
        if risk == "high" and rev in {"partial", "irreversible"}:
            return "SUSPEND"
        if risk in {"high", "medium"}:
            return "REQUEST_CHANGES"
        return "APPROVE"

    def _run_round1_role(
        self,
        *,
        role_id: str,
        diff: str,
        routing_features: dict[str, Any],
        binding: list[PromptAsset],
        llm_client: LLMClient,
        use_mock: bool,
    ) -> tuple[str, dict[str, Any]]:
        if use_mock:
            if role_id == "security_reviewer" and "[[MOCK:SUSPEND]]" in diff:
                text = self._load_fixture("round1_security_reviewer_suspend.md")
            else:
                text = self._load_fixture(f"round1_{role_id}.md")
            return text, {
                "provider": "mock",
                "model": "mock:debate-fixture",
                "agent_id": role_id,
                "round_name": "round1",
                "role_id": role_id,
                "started_at": datetime.now(timezone.utc).isoformat(),
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
            }

        system_prompt = self._build_role_system_prompt(binding, role_id)
        user_payload = (
            "Round: 1\n"
            f"Role: {role_id}\n"
            f"Routing Features: {routing_features}\n"
            "Diff:\n"
            f"{diff}\n"
            "Output concise role assessment text containing one of APPROVE/REQUEST_CHANGES/SUSPEND."
        )
        started_at = datetime.now(timezone.utc).isoformat()
        t0 = perf_counter()
        try:
            claim, meta = llm_client.generate_claim_with_meta(
                diff=user_payload,
                system_prompt=system_prompt,
                agent_id=role_id,
                round_name="round1",
                role_id=role_id,
            )
            if not isinstance(claim, dict):
                raise DebateExecutorError("round1 llm payload is not object")
            verdict = self._claim_to_verdict_keyword(claim)
            conclusion = str(claim.get("conclusion", "No conclusion provided.")).strip()
            return f"{conclusion}\nVERDICT: {verdict}", meta
        except LlmAuthError:
            raise
        except Exception as exc:
            if self._is_role_retryable(exc):
                return self._degraded_role_output(role_id, exc), self._degraded_meta(
                    role_id=role_id,
                    round_name="round1",
                    started_at=started_at,
                    duration_ms=int((perf_counter() - t0) * 1000),
                    exc=exc,
                )
            raise

    def _build_round2_user_input(
        self,
        *,
        diff: str,
        routing_features: dict[str, Any],
        role_id: str,
        round1_outputs: dict[str, str],
    ) -> str:
        others = [self._short_claim_for_round2(self._anonymize_text(round1_outputs[r])) for r in ROUND1_ROLE_IDS if r != role_id]
        lines = [
            "Round: 2",
            f"Routing Features: {routing_features}",
            "Diff:",
            diff,
            "",
            "Anonymized prior claims:",
        ]
        for i, txt in enumerate(others, start=1):
            lines.append(f"claim_{i}: {txt}")
        lines.append("")
        lines.append("Provide cross-critique text with revised verdict keyword if changed.")
        return self._truncate("\n".join(lines), self._round2_payload_char_limit())

    @staticmethod
    def _anonymize_text(text: str) -> str:
        out = str(text)
        for rid in ROUND1_ROLE_IDS:
            out = out.replace(rid, "reviewer")
        return out

    def _run_round2_role(
        self,
        *,
        role_id: str,
        diff: str,
        routing_features: dict[str, Any],
        round1_outputs: dict[str, str],
        binding: list[PromptAsset],
        llm_client: LLMClient,
        use_mock: bool,
    ) -> tuple[str, dict[str, Any]]:
        if use_mock:
            return self._load_fixture("round2_cross_critique.md"), {
                "provider": "mock",
                "model": "mock:debate-fixture",
                "agent_id": role_id,
                "round_name": "round2",
                "role_id": role_id,
                "started_at": datetime.now(timezone.utc).isoformat(),
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
            }

        system_prompt = self._build_role_system_prompt(binding, role_id)
        user_payload = self._build_round2_user_input(
            diff=diff,
            routing_features=routing_features,
            role_id=role_id,
            round1_outputs=round1_outputs,
        )
        started_at = datetime.now(timezone.utc).isoformat()
        t0 = perf_counter()
        try:
            claim, meta = llm_client.generate_claim_with_meta(
                diff=user_payload,
                system_prompt=system_prompt,
                agent_id=role_id,
                round_name="round2",
                role_id=role_id,
            )
            if not isinstance(claim, dict):
                raise DebateExecutorError("round2 llm payload is not object")
            verdict = self._claim_to_verdict_keyword(claim)
            conclusion = str(claim.get("conclusion", "No critique provided.")).strip()
            return f"REVISED_VERDICT: {verdict}\n{conclusion}", meta
        except LlmAuthError:
            raise
        except Exception as exc:
            if self._is_role_retryable(exc):
                return self._degraded_role_output(role_id, exc), self._degraded_meta(
                    role_id=role_id,
                    round_name="round2",
                    started_at=started_at,
                    duration_ms=int((perf_counter() - t0) * 1000),
                    exc=exc,
                )
            raise

    @staticmethod
    def _determine_mode(round1_outputs: dict[str, str]) -> Round3Mode:
        verdicts = [DebateExecutor._extract_round1_verdict(t) for t in round1_outputs.values()]
        if any(v == "SUSPEND" for v in verdicts):
            return "suspend"

        approve = sum(1 for v in verdicts if v == "APPROVE")
        req = sum(1 for v in verdicts if v == "REQUEST_CHANGES")

        if req >= approve:
            return "majority_with_minority"
        return "consensus"

    @staticmethod
    def _first_sentence(text: str) -> str:
        t = text.strip()
        if not t:
            return "Debate completed."
        m = re.split(r"(?<=[.!?])\s+", t, maxsplit=1)
        return m[0].strip() if m and m[0].strip() else "Debate completed."

    @staticmethod
    def _round_timeout_seconds(llm_policy: LlmPolicy | None) -> int:
        if llm_policy is None:
            return 60
        if llm_policy.debate.round_timeout_seconds is not None:
            return max(1, int(llm_policy.debate.round_timeout_seconds))
        return max(1, int(llm_policy.timeout_seconds) * 2)

    async def _run_with_timeout(self, coro: Any, round_name: str) -> _T:
        timeout = self._round_timeout_seconds(self.llm_policy)
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except TimeoutError as exc:
            raise DebateRoundTimeoutError(f"{round_name} timeout after {timeout}s") from exc

    def _extract_summary(self, raw_round3_text: str, session_dir: Path) -> str:
        lines = [ln.strip() for ln in str(raw_round3_text).splitlines()]
        body = [ln for ln in lines if ln and not ln.startswith("#")]
        if body:
            return body[0]

        fallback = str(raw_round3_text).strip()[:500]
        if not fallback:
            fallback = "Debate summary fallback: empty upstream output."
        self._emit_warning_event(
            session_dir,
            "debate_summary_extraction_failed",
            {
                "reason": "no_non_heading_summary",
                "raw_len": len(str(raw_round3_text)),
                "fallback_len": len(fallback),
            },
        )
        return fallback

    def _build_round3_user_payload(
        self,
        *,
        diff: str,
        routing_features: dict[str, Any],
        round1_outputs: dict[str, str],
        round2_outputs: dict[str, str],
    ) -> str:
        verdicts = {role_id: self._extract_round1_verdict(round1_outputs[role_id]) for role_id in ROUND1_ROLE_IDS}
        payload = {
            "round": 3,
            "routing_features": routing_features,
            "diff": self._truncate(diff, 1200),
            "round1_verdicts": verdicts,
            "round1_snippets": {role_id: self._truncate(round1_outputs[role_id], 240) for role_id in ROUND1_ROLE_IDS},
            "round2_snippets": {role_id: self._truncate(round2_outputs[role_id], 240) for role_id in ROUND1_ROLE_IDS},
        }
        text = json.dumps(payload, ensure_ascii=True)
        return self._truncate(text, self._round3_payload_char_limit())

    def _run_round3_orchestrator(
        self,
        *,
        diff: str,
        routing_features: dict[str, Any],
        round1_outputs: dict[str, str],
        round2_outputs: dict[str, str],
        binding: list[PromptAsset],
        llm_client: LLMClient,
        use_mock: bool,
    ) -> tuple[str, dict[str, Any]]:
        if use_mock:
            return self._load_fixture("round3_orchestrator.md"), {
                "provider": "mock",
                "model": "mock:debate-fixture",
                "agent_id": "orchestrator_debate",
                "round_name": "round3",
                "role_id": "orchestrator_debate",
                "started_at": datetime.now(timezone.utc).isoformat(),
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
            }

        system_prompt = self._build_orchestrator_system_prompt(binding)
        user_payload = self._build_round3_user_payload(
            diff=diff,
            routing_features=routing_features,
            round1_outputs=round1_outputs,
            round2_outputs=round2_outputs,
        )

        claim, meta = llm_client.generate_claim_with_meta(
            diff=user_payload,
            system_prompt=system_prompt,
            agent_id="orchestrator_debate",
            round_name="round3",
            role_id="orchestrator_debate",
        )
        if not isinstance(claim, dict):
            raise DebateExecutorError("round3 llm payload is not object")
        return str(claim.get("conclusion", "")).strip(), meta

    @staticmethod
    def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")

    def _write_debate_metrics(
        self,
        *,
        session: Path,
        call_rows: list[dict[str, Any]],
        round1_ms: int,
        round2_ms: int,
        round3_ms: int,
        total_ms: int,
        decision: str,
    ) -> None:
        status_hist = Counter()
        for row in call_rows:
            code = row.get("final_status_code")
            if code is not None:
                status_hist[str(code)] += 1
        failed = [r for r in call_rows if r.get("outcome") != "ok"]
        prompt_vals = [int(r["prompt_tokens"]) for r in call_rows if isinstance(r.get("prompt_tokens"), int)]
        completion_vals = [int(r["completion_tokens"]) for r in call_rows if isinstance(r.get("completion_tokens"), int)]
        total_vals = [int(r["total_tokens"]) for r in call_rows if isinstance(r.get("total_tokens"), int)]
        cost_vals = [float(r["estimated_cost_usd"]) for r in call_rows if isinstance(r.get("estimated_cost_usd"), (int, float))]
        cost_alert_total = int(sum(1 for r in call_rows if bool(r.get("cost_alert_exceeded"))))
        metrics = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_calls": len(call_rows),
            "success_calls": len(call_rows) - len(failed),
            "failed_calls": len(failed),
            "round1_ms": round1_ms,
            "round2_ms": round2_ms,
            "round3_ms": round3_ms,
            "total_ms": total_ms,
            "retry_total": int(sum(int(r.get("retry_count", 0)) for r in call_rows)),
            "timeout_total": int(sum(1 for r in call_rows if r.get("outcome") == "timeout")),
            "status_code_histogram": dict(status_hist),
            "decision": decision,
            "prompt_tokens": int(sum(prompt_vals)) if prompt_vals else None,
            "completion_tokens": int(sum(completion_vals)) if completion_vals else None,
            "total_tokens": int(sum(total_vals)) if total_vals else None,
            "estimated_cost_usd": round(sum(cost_vals), 8) if cost_vals else None,
            "cost_alert_exceeded_calls": cost_alert_total,
        }
        (session / "debate").mkdir(parents=True, exist_ok=True)
        (session / "debate" / "debate_metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    def _resolve_session_dir(self, session_dir: str | Path | None) -> Path:
        if session_dir is not None:
            p = Path(session_dir)
        else:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            p = Path("sessions/debate/runs") / f"run_{stamp}"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def run(
        self,
        *,
        diff: str,
        routing_features: dict[str, Any],
        binding: list[PromptAsset],
        llm_client: LLMClient,
        session_dir: str | Path | None = None,
        use_mock: bool = False,
        progress_cb: Callable[[str, str, float | None], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        cancel_after_round: int | None = None,
    ) -> DebateVerdict:
        if not binding:
            raise DebateExecutorError("binding assets are required")

        session = self._resolve_session_dir(session_dir)

        def _notify(round_name: str, phase: str, elapsed: float | None = None) -> None:
            if progress_cb is not None:
                progress_cb(round_name, phase, elapsed)

        def _raise_if_cancelled() -> None:
            if cancel_check is not None and bool(cancel_check()):
                raise DebateCancelledError("workflow_cancelled")

        def _raise_if_cancel_after_round_done(round_no: int) -> None:
            if cancel_after_round in {1, 2} and round_no >= int(cancel_after_round):
                raise DebateCancelledError(
                    f"workflow_cancelled_after_round_{round_no}",
                    cancelled_at_round=round_no,
                )

        async def _compute_round1() -> tuple[dict[str, str], list[dict[str, Any]]]:
            sem = asyncio.Semaphore(self._max_parallel_roles())

            async def _one(role_id: str) -> tuple[str, str, dict[str, Any]]:
                async with sem:
                    _raise_if_cancelled()
                    text, meta = await asyncio.to_thread(
                        self._run_round1_role,
                        role_id=role_id,
                        diff=diff,
                        routing_features=routing_features,
                        binding=binding,
                        llm_client=llm_client,
                        use_mock=use_mock,
                    )
                    return role_id, text, meta

            rows = await asyncio.gather(*[_one(r) for r in ROUND1_ROLE_IDS])
            out: dict[str, str] = {}
            call_rows: list[dict[str, Any]] = []
            for role_id, text, meta in rows:
                out[role_id] = text
                call_rows.append(meta)
            return out, call_rows

        async def _compute_round2(round1_outputs: dict[str, str]) -> tuple[dict[str, str], list[dict[str, Any]]]:
            sem = asyncio.Semaphore(self._max_parallel_roles())

            async def _one(role_id: str) -> tuple[str, str, dict[str, Any]]:
                async with sem:
                    _raise_if_cancelled()
                    text, meta = await asyncio.to_thread(
                        self._run_round2_role,
                        role_id=role_id,
                        diff=diff,
                        routing_features=routing_features,
                        round1_outputs=round1_outputs,
                        binding=binding,
                        llm_client=llm_client,
                        use_mock=use_mock,
                    )
                    return role_id, text, meta

            rows = await asyncio.gather(*[_one(r) for r in ROUND1_ROLE_IDS])
            out: dict[str, str] = {}
            call_rows: list[dict[str, Any]] = []
            for role_id, text, meta in rows:
                out[role_id] = text
                call_rows.append(meta)
            return out, call_rows

        async def _compute_round3(
            round1_outputs: dict[str, str], round2_outputs: dict[str, str]
        ) -> tuple[str, dict[str, Any]]:
            return await asyncio.to_thread(
                self._run_round3_orchestrator,
                diff=diff,
                routing_features=routing_features,
                round1_outputs=round1_outputs,
                round2_outputs=round2_outputs,
                binding=binding,
                llm_client=llm_client,
                use_mock=use_mock,
            )

        t_total = perf_counter()
        llm_call_rows: list[dict[str, Any]] = []
        round1_ms = 0
        round2_ms = 0
        round3_ms = 0
        try:
            _raise_if_cancelled()
            _notify("round1", "start", None)
            t0 = perf_counter()
            round1_outputs, round1_call_rows = asyncio.run(self._run_with_timeout(_compute_round1(), "round1"))
            round1_ms = int((perf_counter() - t0) * 1000)
            llm_call_rows.extend(round1_call_rows)
            _notify("round1", "done", round1_ms / 1000.0)
            _raise_if_cancel_after_round_done(1)

            _raise_if_cancelled()
            _notify("round2", "start", None)
            t0 = perf_counter()
            round2_outputs, round2_call_rows = asyncio.run(self._run_with_timeout(_compute_round2(round1_outputs), "round2"))
            round2_ms = int((perf_counter() - t0) * 1000)
            llm_call_rows.extend(round2_call_rows)
            _notify("round2", "done", round2_ms / 1000.0)
            _raise_if_cancel_after_round_done(2)

            _raise_if_cancelled()
            _notify("round3", "start", None)
            t0 = perf_counter()
            mode = self._determine_mode(round1_outputs)
            round3_raw, round3_meta = asyncio.run(
                self._run_with_timeout(_compute_round3(round1_outputs, round2_outputs), "round3")
            )
            round3_summary = self._extract_summary(round3_raw, session)
            round3_ms = int((perf_counter() - t0) * 1000)
            llm_call_rows.append(round3_meta)
            _notify("round3", "done", round3_ms / 1000.0)
        except DebateCancelledError:
            for row in llm_call_rows:
                self._append_jsonl(session / "debate" / "llm_calls.jsonl", row)
            self._write_debate_metrics(
                session=session,
                call_rows=llm_call_rows,
                round1_ms=round1_ms,
                round2_ms=round2_ms,
                round3_ms=round3_ms,
                total_ms=int((perf_counter() - t_total) * 1000),
                decision="CANCELLED",
            )
            raise

        minority_view = None
        if mode == "majority_with_minority":
            minority_view = "Minority requests additional verification before merge."

        async def _run_round_files() -> tuple[Path, Path, Path]:
            r1 = await self._engine.round1_parallel_claims(session, round1_outputs)
            r2 = await self._engine.round2_cross_critique(session, round2_outputs)
            r3 = await self._engine.round3_converge(
                session,
                mode=mode,
                summary=round3_summary,
                minority_view=minority_view,
            )
            return r1, r2, r3

        round1_path, round2_path, round3_path = asyncio.run(_run_round_files())

        if mode == "suspend":
            decision: Literal["APPROVE", "REQUEST_CHANGES", "SUSPEND"] = "SUSPEND"
            recommendation = None
        elif mode == "majority_with_minority":
            decision = "REQUEST_CHANGES"
            recommendation = self._first_sentence(round3_summary)
        else:
            decision = "APPROVE"
            recommendation = self._first_sentence(round3_summary)

        if decision == "SUSPEND":
            recommendation = None

        for row in llm_call_rows:
            self._append_jsonl(session / "debate" / "llm_calls.jsonl", row)
        self._write_debate_metrics(
            session=session,
            call_rows=llm_call_rows,
            round1_ms=round1_ms,
            round2_ms=round2_ms,
            round3_ms=round3_ms,
            total_ms=int((perf_counter() - t_total) * 1000),
            decision=decision,
        )

        return DebateVerdict(
            decision=decision,
            session_dir=str(session.resolve()),
            round1_path=str(round1_path.resolve()),
            round2_path=str(round2_path.resolve()),
            round3_path=str(round3_path.resolve()),
            recommendation=recommendation,
        )
