from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agora.models import RoutingDecision, TaskFeatures


@dataclass(frozen=True)
class Rule:
    name: str
    priority: int
    match: dict[str, Any]
    route: str
    permissions_scope: str
    fallback_chain: list[str]
    debate_trigger: dict[str, Any]


class RuleEngine:
    def __init__(self, rules: list[Rule]):
        self._rules = sorted(rules, key=lambda r: r.priority)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RuleEngine":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        raw_rules = data.get("rules", [])
        rules = []
        for item in raw_rules:
            rules.append(
                Rule(
                    name=item["name"],
                    priority=int(item.get("priority", 9999)),
                    match=item.get("match", {}),
                    route=item["route"],
                    permissions_scope=item.get("permissions_scope", "scope_unknown_intersection"),
                    fallback_chain=item.get("fallback_chain", []),
                    debate_trigger=item.get("debate_trigger", {}),
                )
            )
        return cls(rules)

    def route(
        self,
        features: TaskFeatures,
        command_text: str = "",
        subagent_disagreement: bool = False,
    ) -> RoutingDecision:
        for rule in self._rules:
            if self._matches(rule, features, command_text):
                debate_triggered = self._debate_triggered(rule, features, subagent_disagreement)
                return RoutingDecision(
                    workflow_type=rule.route,
                    permissions_scope=rule.permissions_scope,
                    debate_triggered=debate_triggered,
                    fallback_chain=rule.fallback_chain,
                    matched_rule=rule.name,
                    feature_confidence=features.confidence,
                )
        raise RuntimeError("no routing rule matched")

    def _matches(self, rule: Rule, features: TaskFeatures, command_text: str) -> bool:
        cond = rule.match

        keywords = cond.get("keywords")
        if keywords:
            lower = command_text.lower()
            return any(str(k).lower() in lower for k in keywords)

        if "task_intent" in cond and not _match_value(cond["task_intent"], features.task_intent):
            return False
        if "risk_level" in cond and not _match_value(cond["risk_level"], features.risk_level):
            return False
        if "reversibility" in cond and not _match_value(cond["reversibility"], features.reversibility):
            return False
        if "requires_tools" in cond and not _match_value(cond["requires_tools"], features.requires_tools):
            return False

        return True

    def _debate_triggered(
        self, rule: Rule, features: TaskFeatures, subagent_disagreement: bool
    ) -> bool:
        dt = rule.debate_trigger
        if not dt:
            return False

        hits: list[bool] = []
        if "risk_level" in dt:
            hits.append(_match_value(dt["risk_level"], features.risk_level))

        irreversibility_values = dt.get("irreversibility")
        if irreversibility_values is not None:
            hits.append(_match_value(irreversibility_values, features.reversibility))

        if dt.get("subagent_disagreement") is True:
            hits.append(subagent_disagreement)

        return any(hits) if hits else False


def _match_value(expected: Any, actual: Any) -> bool:
    if isinstance(expected, list):
        return actual in expected
    return actual == expected
