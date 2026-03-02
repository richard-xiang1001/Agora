from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agora.debate_executor import DebateExecutor
from agora.llm_client import LLMClient, MockLLMClient, LlmPolicy
from agora.prompt_registry import load_catalog


class _Status429Error(RuntimeError):
    status_code = 429


class _FlakyLLMClient(LLMClient):
    @property
    def source(self) -> str:
        return 'mock:flaky'

    def generate_claim(self, diff: str, system_prompt: str, agent_id: str) -> dict[str, object]:
        _ = (diff, system_prompt)
        return {
            'agent_id': agent_id,
            'task_intent': 'code_review',
            'risk_level': 'medium',
            'reversibility': 'partial',
            'tool_need': False,
            'conclusion': 'Needs follow-up checks.',
            'evidence': ['x'],
            'assumptions': ['x'],
            'confidence': 'medium',
        }

    def generate_claim_with_meta(
        self,
        *,
        diff: str,
        system_prompt: str,
        agent_id: str,
        round_name: str | None = None,
        role_id: str | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        if role_id == 'security_reviewer' and round_name in {'round1', 'round2'}:
            raise _Status429Error('rate limited')
        claim = self.generate_claim(diff=diff, system_prompt=system_prompt, agent_id=agent_id)
        meta = {
            'provider': 'mock',
            'model': 'mock:flaky',
            'agent_id': agent_id,
            'round_name': round_name,
            'role_id': role_id,
            'started_at': '2026-01-01T00:00:00+00:00',
            'duration_ms': 1,
            'attempts': 1,
            'retry_count': 0,
            'final_status_code': None,
            'error_type': None,
            'outcome': 'ok',
        }
        return claim, meta


class DebateExecutorObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_catalog('config/prompt_catalog.yaml')
        self.binding = self.registry.resolve_profile('profile.debate_code_review')
        self.features = {
            'task_intent': 'code_review',
            'risk_level': 'medium',
            'reversibility': 'partial',
            'requires_tools': False,
            'confidence': 0.9,
        }

    def test_mock_mode_writes_llm_calls_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            policy = LlmPolicy(
                schema_version='1.0',
                provider='openrouter',
                mode='mock',
                model='qwen/qwen3-4b:free',
                timeout_seconds=30,
                max_retries=1,
                retry_on=[500],
                fallback_on_error=False,
            )
            verdict = DebateExecutor(prompt_root_dir='.', llm_policy=policy).run(
                diff='fix: remove unused import',
                routing_features=self.features,
                binding=self.binding,
                llm_client=MockLLMClient(Path('tests/fixtures/mock_llm_responses')),
                session_dir=Path(td) / 'run_obs_mock',
                use_mock=True,
            )
            calls = Path(verdict.session_dir) / 'debate' / 'llm_calls.jsonl'
            metrics = Path(verdict.session_dir) / 'debate' / 'debate_metrics.json'
            self.assertTrue(calls.exists())
            self.assertTrue(metrics.exists())
            rows = [json.loads(x) for x in calls.read_text(encoding='utf-8').splitlines() if x.strip()]
            self.assertGreaterEqual(len(rows), 13)
            self.assertIn('duration_ms', rows[0])
            data = json.loads(metrics.read_text(encoding='utf-8'))
            self.assertEqual(data['total_calls'], len(rows))
            self.assertIn('decision', data)

    def test_retryable_role_errors_are_degraded_and_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            policy = LlmPolicy(
                schema_version='1.0',
                provider='openrouter',
                mode='openrouter',
                model='qwen/qwen3-4b:free',
                timeout_seconds=30,
                max_retries=1,
                retry_on=[500, 502, 503],
                fallback_on_error=False,
            )
            verdict = DebateExecutor(prompt_root_dir='.', llm_policy=policy).run(
                diff='fix: remove unused import',
                routing_features=self.features,
                binding=self.binding,
                llm_client=_FlakyLLMClient(),
                session_dir=Path(td) / 'run_obs_flaky',
                use_mock=False,
            )
            data = json.loads((Path(verdict.session_dir) / 'debate' / 'debate_metrics.json').read_text(encoding='utf-8'))
            self.assertGreaterEqual(data['failed_calls'], 2)
            self.assertGreaterEqual(int(data['status_code_histogram'].get('429', 0)), 2)
            rows = [
                json.loads(x)
                for x in (Path(verdict.session_dir) / 'debate' / 'llm_calls.jsonl').read_text(encoding='utf-8').splitlines()
                if x.strip()
            ]
            self.assertTrue(any(r.get('outcome') == 'retry_exhausted' for r in rows))


if __name__ == '__main__':
    unittest.main()
