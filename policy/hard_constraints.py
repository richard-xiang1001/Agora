from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HardConstraintMatch:
    hit: bool
    rule: str | None


HARD_CONSTRAINT_PATTERNS: dict[str, list[str]] = {
    "mass_harm": [
        "生物武器",
        "化学武器",
        "核武器",
        "terror attack",
        "critical infrastructure sabotage",
    ],
    "severe_abuse": [
        "csam",
        "未成年人性化",
        "人肉搜索",
        "大规模虚假信息",
    ],
    "system_escape": [
        "绕过沙箱",
        "窃取 api key",
        "隐藏日志",
        "后门",
    ],
}


def check_hard_constraints(text: str) -> HardConstraintMatch:
    low = text.lower()
    for rule, patterns in HARD_CONSTRAINT_PATTERNS.items():
        if any(p.lower() in low for p in patterns):
            return HardConstraintMatch(hit=True, rule=rule)
    return HardConstraintMatch(hit=False, rule=None)
