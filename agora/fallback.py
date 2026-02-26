from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from agora.models import FallbackEvent


@dataclass
class ChainState:
    models: list[str]
    current_index: int = 0
    next_retry_at: datetime | None = None

    @property
    def primary(self) -> str:
        return self.models[0]

    @property
    def current(self) -> str:
        return self.models[self.current_index]


class FallbackManager:
    """Minimal fallback manager with switch-over and auto-return to primary."""

    def __init__(self, chains: dict[str, list[str]], base_backoff_seconds: int = 2) -> None:
        if base_backoff_seconds < 1:
            raise ValueError("base_backoff_seconds must be >= 1")
        self._base_backoff_seconds = base_backoff_seconds
        self._chains: dict[str, ChainState] = {}
        for role, models in chains.items():
            if not models:
                raise ValueError(f"fallback chain for role {role!r} cannot be empty")
            self._chains[role] = ChainState(models=models)

    def select_model(self, role: str) -> str:
        state = self._state(role)

        # Auto-return to primary once retry window passes.
        if state.current_index > 0 and state.next_retry_at is not None:
            if datetime.now(timezone.utc) >= state.next_retry_at:
                state.current_index = 0
                state.next_retry_at = None

        return state.current

    def record_failure(self, role: str, error_class: str) -> FallbackEvent:
        state = self._state(role)
        primary = state.primary

        if state.current_index < len(state.models) - 1:
            state.current_index += 1
            recovery_status = "pending"
        else:
            recovery_status = "failed"

        backoff = self._base_backoff_seconds * (2 ** max(0, state.current_index - 1))
        state.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)

        return FallbackEvent(
            primary_model=primary,
            error_class=error_class,
            switchover_model=state.current,
            recovery_status=recovery_status,
            timestamp=datetime.now(timezone.utc),
        )

    def record_recovered(self, role: str) -> None:
        state = self._state(role)
        state.current_index = 0
        state.next_retry_at = None

    def _state(self, role: str) -> ChainState:
        if role not in self._chains:
            raise KeyError(f"unknown fallback role: {role}")
        return self._chains[role]
