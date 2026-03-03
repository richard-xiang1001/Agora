from __future__ import annotations

from pathlib import Path

from agora.llm import (
    DebatePolicy,
    LLMClient,
    LlmAuthError,
    LlmPolicy,
    LlmPolicyError,
    MockLLMClient,
    OpenRouterLLMClient,
    RetryBackoffPolicy,
    load_llm_policy,
    load_model_pricing,
    load_openrouter_api_key,
    openrouter_key_fingerprint,
    retry_delay_seconds,
    validate_openrouter_auth,
)


def _resolve_mock_fixture_dir(root_dir: Path, repo_root: Path) -> Path:
    local = root_dir / "tests" / "fixtures" / "mock_llm_responses"
    if local.exists():
        return local
    repo = repo_root / "tests" / "fixtures" / "mock_llm_responses"
    if repo.exists():
        return repo
    raise LlmPolicyError("mock fixture directory not found")


def build_llm_client(policy: LlmPolicy, *, root_dir: str | Path, repo_root: str | Path) -> LLMClient:
    root = Path(root_dir).resolve()
    repo = Path(repo_root).resolve()
    if policy.mode == "mock":
        return MockLLMClient(_resolve_mock_fixture_dir(root, repo))
    if policy.mode == "openrouter":
        pricing = load_model_pricing(root / "config" / "model_pricing.yaml")
        if not pricing:
            pricing = load_model_pricing(repo / "config" / "model_pricing.yaml")
        return OpenRouterLLMClient(policy, model_pricing=pricing)
    raise LlmPolicyError(f"unsupported llm mode: {policy.mode}")


# Backward-compatible helper name used by tests.
def _retry_delay_seconds(policy: LlmPolicy, retry_index: int) -> float:
    return retry_delay_seconds(policy, retry_index)


__all__ = [
    "DebatePolicy",
    "LLMClient",
    "LlmAuthError",
    "LlmPolicy",
    "LlmPolicyError",
    "MockLLMClient",
    "OpenRouterLLMClient",
    "RetryBackoffPolicy",
    "build_llm_client",
    "load_llm_policy",
    "load_openrouter_api_key",
    "openrouter_key_fingerprint",
    "validate_openrouter_auth",
    "_retry_delay_seconds",
]
