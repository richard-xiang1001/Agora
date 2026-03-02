from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from agora.llm_client import LLMClient
from agora.models import TaskFeatures
from agora.prompt_adapters import compose_subagent_prompt
from agora.prompt_types import PromptAsset


class SubagentExecutorError(RuntimeError):
    pass


class Claim(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    agent_id: str
    task_intent: Literal["code_review", "research", "planning", "general", "unknown"]
    risk_level: Literal["low", "medium", "high"]
    reversibility: Literal["reversible", "partial", "irreversible"]
    tool_need: bool
    conclusion: str
    evidence: list[str]
    assumptions: list[str]
    confidence: Literal["low", "medium", "high"]


class SubagentVerdict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    decision: Literal["APPROVE", "REQUEST_CHANGES", "SUSPEND"]
    hard_flag: bool
    summary: str
    recommendation: str | None
    claim: dict[str, Any]
    model_source: str
    llm_meta: dict[str, Any] | None = None


class SubagentExecutor:
    def __init__(self, *, prompt_root_dir: str = ".") -> None:
        self.prompt_root_dir = prompt_root_dir

    @staticmethod
    def _pick_prompt_text(binding_assets: list[PromptAsset], prefix: str) -> str | None:
        for asset in binding_assets:
            if asset.id.startswith(prefix):
                return asset.text
        return None

    def _build_system_prompt(self, binding_assets: list[PromptAsset]) -> str:
        base_prompt = self._pick_prompt_text(binding_assets, "subagent.base")
        domain_prompt = self._pick_prompt_text(binding_assets, "subagent.domain.code_reviewer")
        if not base_prompt:
            base_prompt = binding_assets[0].text if binding_assets else "You are a rigorous code reviewer."
        if not domain_prompt:
            domain_prompt = base_prompt
        return compose_subagent_prompt(
            base_prompt=base_prompt,
            domain_prompt=domain_prompt,
            output_mode="json_claim_v1",
            root_dir=self.prompt_root_dir,
        )

    @staticmethod
    def _to_decision(claim: Claim) -> tuple[str, bool, str | None]:
        if claim.risk_level == "high" and claim.reversibility in {"partial", "irreversible"}:
            return "SUSPEND", True, None
        if claim.risk_level in {"medium", "high"}:
            return "REQUEST_CHANGES", False, claim.conclusion.strip()
        return "APPROVE", False, claim.conclusion.strip()

    @staticmethod
    def _summary_text(claim: Claim, decision: str) -> str:
        text = claim.conclusion.strip()
        if not text:
            text = "No conclusion provided by model."
        return f"{decision}: {text}"

    def run(
        self,
        *,
        diff: str,
        task_features: TaskFeatures,
        binding_assets: list[PromptAsset],
        llm_client: LLMClient,
    ) -> SubagentVerdict:
        _ = task_features
        system_prompt = self._build_system_prompt(binding_assets)
        raw, llm_meta = llm_client.generate_claim_with_meta(
            diff=diff,
            system_prompt=system_prompt,
            agent_id="subagent-reviewer",
            round_name="subagent",
            role_id="subagent-reviewer",
        )
        if not isinstance(raw, dict):
            raise SubagentExecutorError("llm client returned non-object claim payload")

        try:
            claim = Claim(**raw)
        except ValidationError as exc:
            raise SubagentExecutorError(f"invalid claim payload: {exc}") from exc

        decision, hard_flag, recommendation = self._to_decision(claim)
        return SubagentVerdict(
            decision=decision,
            hard_flag=hard_flag,
            summary=self._summary_text(claim, decision),
            recommendation=recommendation,
            claim=claim.model_dump(mode="json"),
            model_source=llm_client.source,
            llm_meta=llm_meta,
        )
