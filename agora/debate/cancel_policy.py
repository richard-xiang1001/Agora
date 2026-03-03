from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class CancelPolicy:
    cancel_check: Callable[[], bool] | None = None
    cancel_after_round: int | None = None

    def raise_if_requested(self, exc_type: type[Exception]) -> None:
        if self.cancel_check is not None and bool(self.cancel_check()):
            raise exc_type("workflow_cancelled")

    def raise_if_round_done(self, round_no: int, exc_type: type[Exception]) -> None:
        if self.cancel_after_round in {1, 2} and round_no >= int(self.cancel_after_round):
            raise exc_type(f"workflow_cancelled_after_round_{round_no}", cancelled_at_round=round_no)
