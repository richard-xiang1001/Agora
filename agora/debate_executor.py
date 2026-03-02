from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from pathlib import Path
from typing import Any, Callable, Literal, TypeVar

from agora.debate_engine import DebateEngine, Round3Mode
from agora.llm_client import LLMClient, LlmPolicy
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
    ) -> str:
        if use_mock:
            if role_id == "security_reviewer" and "[[MOCK:SUSPEND]]" in diff:
                return self._load_fixture("round1_security_reviewer_suspend.md")
            return self._load_fixture(f"round1_{role_id}.md")

        system_prompt = self._build_role_system_prompt(binding, role_id)
        user_payload = (
            "Round: 1\n"
            f"Role: {role_id}\n"
            f"Routing Features: {routing_features}\n"
            "Diff:\n"
            f"{diff}\n"
            "Output concise role assessment text containing one of APPROVE/REQUEST_CHANGES/SUSPEND."
        )
        claim = llm_client.generate_claim(
            diff=user_payload,
            system_prompt=system_prompt,
            agent_id=role_id,
        )
        if not isinstance(claim, dict):
            raise DebateExecutorError("round1 llm payload is not object")
        verdict = self._claim_to_verdict_keyword(claim)
        conclusion = str(claim.get("conclusion", "No conclusion provided.")).strip()
        return f"{conclusion}\nVERDICT: {verdict}"

    def _build_round2_user_input(
        self,
        *,
        diff: str,
        routing_features: dict[str, Any],
        role_id: str,
        round1_outputs: dict[str, str],
    ) -> str:
        others = [self._anonymize_text(round1_outputs[r]) for r in ROUND1_ROLE_IDS if r != role_id]
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
        return "\n".join(lines)

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
    ) -> str:
        if use_mock:
            return self._load_fixture("round2_cross_critique.md")

        system_prompt = self._build_role_system_prompt(binding, role_id)
        user_payload = self._build_round2_user_input(
            diff=diff,
            routing_features=routing_features,
            role_id=role_id,
            round1_outputs=round1_outputs,
        )
        claim = llm_client.generate_claim(
            diff=user_payload,
            system_prompt=system_prompt,
            agent_id=role_id,
        )
        if not isinstance(claim, dict):
            raise DebateExecutorError("round2 llm payload is not object")
        verdict = self._claim_to_verdict_keyword(claim)
        conclusion = str(claim.get("conclusion", "No critique provided.")).strip()
        return f"REVISED_VERDICT: {verdict}\n{conclusion}"

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
    ) -> str:
        if use_mock:
            return self._load_fixture("round3_orchestrator.md")

        system_prompt = self._build_orchestrator_system_prompt(binding)
        lines = [
            "Round: 3",
            f"Routing Features: {routing_features}",
            "Diff:",
            diff,
            "",
            "Round1 outputs:",
        ]
        for role_id in ROUND1_ROLE_IDS:
            lines.append(f"- {role_id}: {round1_outputs[role_id]}")
        lines.append("Round2 outputs:")
        for role_id in ROUND1_ROLE_IDS:
            lines.append(f"- {role_id}: {round2_outputs[role_id]}")
        lines.append("Provide one concise convergence summary.")
        user_payload = "\n".join(lines)

        claim = llm_client.generate_claim(
            diff=user_payload,
            system_prompt=system_prompt,
            agent_id="orchestrator_debate",
        )
        if not isinstance(claim, dict):
            raise DebateExecutorError("round3 llm payload is not object")
        return str(claim.get("conclusion", "")).strip()

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
    ) -> DebateVerdict:
        if not binding:
            raise DebateExecutorError("binding assets are required")

        session = self._resolve_session_dir(session_dir)

        def _notify(round_name: str, phase: str, elapsed: float | None = None) -> None:
            if progress_cb is not None:
                progress_cb(round_name, phase, elapsed)

        async def _compute_round1() -> dict[str, str]:
            out: dict[str, str] = {}
            for role_id in ROUND1_ROLE_IDS:
                out[role_id] = await asyncio.to_thread(
                    self._run_round1_role,
                    role_id=role_id,
                    diff=diff,
                    routing_features=routing_features,
                    binding=binding,
                    llm_client=llm_client,
                    use_mock=use_mock,
                )
            return out

        async def _compute_round2(round1_outputs: dict[str, str]) -> dict[str, str]:
            out: dict[str, str] = {}
            for role_id in ROUND1_ROLE_IDS:
                out[role_id] = await asyncio.to_thread(
                    self._run_round2_role,
                    role_id=role_id,
                    diff=diff,
                    routing_features=routing_features,
                    round1_outputs=round1_outputs,
                    binding=binding,
                    llm_client=llm_client,
                    use_mock=use_mock,
                )
            return out

        async def _compute_round3(round1_outputs: dict[str, str], round2_outputs: dict[str, str]) -> str:
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

        _notify("round1", "start", None)
        t0 = perf_counter()
        round1_outputs = asyncio.run(self._run_with_timeout(_compute_round1(), "round1"))
        _notify("round1", "done", perf_counter() - t0)

        _notify("round2", "start", None)
        t0 = perf_counter()
        round2_outputs = asyncio.run(self._run_with_timeout(_compute_round2(round1_outputs), "round2"))
        _notify("round2", "done", perf_counter() - t0)

        _notify("round3", "start", None)
        t0 = perf_counter()
        mode = self._determine_mode(round1_outputs)
        round3_raw = asyncio.run(self._run_with_timeout(_compute_round3(round1_outputs, round2_outputs), "round3"))
        round3_summary = self._extract_summary(round3_raw, session)
        _notify("round3", "done", perf_counter() - t0)

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

        return DebateVerdict(
            decision=decision,
            session_dir=str(session.resolve()),
            round1_path=str(round1_path.resolve()),
            round2_path=str(round2_path.resolve()),
            round3_path=str(round3_path.resolve()),
            recommendation=recommendation,
        )
