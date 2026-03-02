from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class StructuredConstraintDescriptor:
    rule_id: str
    intent_categories: list[str]
    pattern_type: str
    pattern: str
    severity: str
    fallback_to_keyword: bool = True


@dataclass(frozen=True)
class HardConstraintMatch:
    hit: bool
    rule: str | None
    constraint_match_path: Literal["semantic", "regex", "keyword", "none"] = "none"


_LEETSPEAK_MAP = str.maketrans({
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "@": "a",
    "$": "s",
})


HARD_CONSTRAINT_KEYWORDS: dict[str, list[str]] = {
    "mass_harm": [
        "生物武器",
        "化学武器",
        "核武器",
        "terror attack",
        "critical infrastructure sabotage",
        "bioweapon",
        "chemical weapon",
        "nuclear weapon",
    ],
    "severe_abuse": [
        "csam",
        "未成年人性化",
        "人肉搜索",
        "大规模虚假信息",
        "doxx",
        "sexualize minor",
        "minor sexual content",
    ],
    "system_escape": [
        "绕过沙箱",
        "窃取 api key",
        "隐藏日志",
        "后门",
        "bypass sandbox",
        "steal api key",
        "exfiltrate api key",
        "hide logs",
        "backdoor",
    ],
}


STRUCTURED_CONSTRAINTS: list[StructuredConstraintDescriptor] = [
    StructuredConstraintDescriptor(
        rule_id="mass_harm",
        intent_categories=["bio_weapon", "chemical_weapon", "nuclear_weapon", "terror_attack"],
        pattern_type="semantic_label",
        pattern="mass_harm",
        severity="hard_block",
    ),
    StructuredConstraintDescriptor(
        rule_id="mass_harm",
        intent_categories=["bio_weapon", "chemical_weapon", "nuclear_weapon", "terror_attack"],
        pattern_type="regex",
        pattern=r"(生\s*物\s*武\s*器|化\s*学\s*武\s*器|核\s*武\s*器|bio\s*weapon|chemical\s*weapon|nuclear\s*weapon|terror\s*attack|critical\s*infrastructure\s*sabotage)",
        severity="hard_block",
    ),
    StructuredConstraintDescriptor(
        rule_id="mass_harm",
        intent_categories=["bio_weapon", "chemical_weapon", "nuclear_weapon", "terror_attack"],
        pattern_type="keyword",
        pattern="mass_harm",
        severity="hard_block",
    ),
    StructuredConstraintDescriptor(
        rule_id="severe_abuse",
        intent_categories=["csam", "doxxing", "minor_sexualization"],
        pattern_type="semantic_label",
        pattern="severe_abuse",
        severity="hard_block",
    ),
    StructuredConstraintDescriptor(
        rule_id="severe_abuse",
        intent_categories=["csam", "doxxing", "minor_sexualization"],
        pattern_type="regex",
        pattern=r"(c\s*s\s*a\s*m|未\s*成\s*年\s*人?\s*性\s*化|人\s*肉\s*搜\s*索|doxx|sexuali[sz]e\s*minor|minor\s*sexual\s*content)",
        severity="hard_block",
    ),
    StructuredConstraintDescriptor(
        rule_id="severe_abuse",
        intent_categories=["csam", "doxxing", "minor_sexualization"],
        pattern_type="keyword",
        pattern="severe_abuse",
        severity="hard_block",
    ),
    StructuredConstraintDescriptor(
        rule_id="system_escape",
        intent_categories=["sandbox_escape", "credential_exfiltration", "log_tampering", "backdoor"],
        pattern_type="semantic_label",
        pattern="system_escape",
        severity="hard_block",
    ),
    StructuredConstraintDescriptor(
        rule_id="system_escape",
        intent_categories=["sandbox_escape", "credential_exfiltration", "log_tampering", "backdoor"],
        pattern_type="regex",
        pattern=r"(绕\s*过\s*沙\s*箱|bypass\s*sandbox|窃\s*取\s*a\s*p\s*i\s*key|steal\s*api\s*key|exfiltrate\s*api\s*key|隐藏\s*日\s*志|hide\s*logs|back\s*door|后\s*门)",
        severity="hard_block",
    ),
    StructuredConstraintDescriptor(
        rule_id="system_escape",
        intent_categories=["sandbox_escape", "credential_exfiltration", "log_tampering", "backdoor"],
        pattern_type="keyword",
        pattern="system_escape",
        severity="hard_block",
    ),
]


def _normalize_text(text: str) -> str:
    norm = unicodedata.normalize("NFKC", text).lower().translate(_LEETSPEAK_MAP)
    return norm


def _compact_text(text: str) -> str:
    return re.sub(r"[\s_\-\.]+", "", _normalize_text(text))


def _semantic_match(rule_id: str, norm: str, compact: str) -> bool:
    joined = f"{norm} {compact}"
    if rule_id == "mass_harm":
        terms = ["bio", "chemical", "nuclear", "terror", "生物武器", "化学武器", "核武器"]
    elif rule_id == "severe_abuse":
        terms = ["csam", "doxx", "minorsexual", "未成年人性化", "人肉搜索"]
    elif rule_id == "system_escape":
        terms = ["bypasssandbox", "apikey", "backdoor", "绕过沙箱", "后门", "隐藏日志"]
    else:
        terms = []
    return any(t in joined for t in terms)


def _keyword_match(rule_id: str, norm: str, compact: str) -> bool:
    for keyword in HARD_CONSTRAINT_KEYWORDS.get(rule_id, []):
        k = _normalize_text(keyword)
        if k in norm or _compact_text(k) in compact:
            return True
    return False


def _evaluate_rule(rule_id: str, norm: str, compact: str) -> HardConstraintMatch:
    descriptors = [d for d in STRUCTURED_CONSTRAINTS if d.rule_id == rule_id and d.severity == "hard_block"]

    for desc in descriptors:
        if desc.pattern_type != "semantic_label":
            continue
        if _semantic_match(rule_id, norm, compact):
            return HardConstraintMatch(hit=True, rule=rule_id, constraint_match_path="semantic")

    for desc in descriptors:
        if desc.pattern_type != "regex":
            continue
        if re.search(desc.pattern, norm, flags=re.IGNORECASE):
            return HardConstraintMatch(hit=True, rule=rule_id, constraint_match_path="regex")

    if any(d.fallback_to_keyword for d in descriptors):
        if _keyword_match(rule_id, norm, compact):
            return HardConstraintMatch(hit=True, rule=rule_id, constraint_match_path="keyword")

    return HardConstraintMatch(hit=False, rule=None, constraint_match_path="none")


def check_hard_constraints(text: str) -> HardConstraintMatch:
    norm = _normalize_text(text)
    compact = _compact_text(text)
    for rule_id in HARD_CONSTRAINT_KEYWORDS:
        match = _evaluate_rule(rule_id, norm, compact)
        if match.hit:
            return match
    return HardConstraintMatch(hit=False, rule=None, constraint_match_path="none")
