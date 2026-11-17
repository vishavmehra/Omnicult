"""Risk Check severity rules, version risk-rules-v1. Deterministic code: a model never chooses severity or "blocks Go".

A finding's severity comes from its category and its evidence, by these steps (the applied steps are stored with the
finding, so every severity can be explained):

  R1 base       the category's base level (table below).
  R2 ad code    +1 when at least one cited ad-code entry exists in the reference index and fits the category's topics.
  R3 claim      +1 when at least one cited region claim is observed or calculated and has moderate or high effective
                confidence. Interpretations, synthetic and unverified claims never escalate.
  R4 hard claim +1 for claim categories when the verified quote carries an absolute, numeric or comparative claim
                (English patterns only; quotes in other languages get no R4 step).
  R5 cap        without R2 or R3 a model finding is capped at medium: model interpretation alone is never "high".
  R6 ceiling    severity never exceeds high.
  R7 blocks Go  blocks_go is true when severity is high and the category can block (table below).

A deterministic brand-rule hit (a prohibited term found verbatim) is high and blocks Go; it is a rule, not an opinion.
Severity is not a probability and not a legal conclusion.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

RULES_VERSION = "risk-rules-v1"
Severity = Literal["low", "medium", "high"]
LEVELS: tuple[Severity, ...] = ("low", "medium", "high")
ConfidenceLabel = Literal["insufficient", "limited", "moderate"]
RiskCategory = Literal[
    "brand_rule", "unsubstantiated_claim", "health_nutrition_claim", "comparative_claim", "children_safety",
    "unsafe_depiction", "offensive_content", "stereotype_or_derision", "disclaimer_issue", "synthetic_media_disclosure",
    "regional_sensitivity", "language_ambiguity", "other",
]
CLAIM_CATEGORIES = frozenset({"unsubstantiated_claim", "health_nutrition_claim", "comparative_claim"})

# category -> (base level, can block Go, ad-code topics that fit it)
CATEGORY_RULES: dict[str, tuple[Severity, bool, frozenset[str]]] = {
    "brand_rule": ("high", True, frozenset()),
    "unsubstantiated_claim": ("medium", True, frozenset({"claims", "substantiation", "misleading", "pricing_offers", "green_claims", "disclaimers"})),
    "health_nutrition_claim": ("medium", True, frozenset({"health_food", "claims", "substantiation", "misleading"})),
    "comparative_claim": ("medium", True, frozenset({"comparisons", "claims", "substantiation", "brand_names"})),
    "children_safety": ("medium", True, frozenset({"children", "safety", "health_food"})),
    "unsafe_depiction": ("medium", True, frozenset({"safety", "children"})),
    "offensive_content": ("medium", True, frozenset({"offence", "stereotypes"})),
    "stereotype_or_derision": ("medium", True, frozenset({"stereotypes", "offence"})),
    "disclaimer_issue": ("low", False, frozenset({"disclaimers", "claims"})),
    "synthetic_media_disclosure": ("medium", True, frozenset({"synthetic_media", "disclaimers", "claims"})),
    "regional_sensitivity": ("low", True, frozenset({"offence", "stereotypes"})),
    "language_ambiguity": ("low", False, frozenset({"misleading", "claims"})),
    "other": ("low", False, frozenset()),
}

HARD_CLAIM = re.compile(
    r"(\b100\s?%|\b\d+(?:\.\d+)?\s?%|\bguarantee[ds]?\b|\brisk[- ]free\b|\bno side effects?\b|\bclinically proven\b|"
    r"\bscientifically proven\b|\bdoctor[- ]recommended\b|\b(?:cures?|heals?|reverses?)\b|\bmiracle\b|"
    r"(?<![a-z])(?:no\.?\s?1|number one|#1)(?![a-z0-9])|\bbest in (?:india|class|the world)\b|\bbetter than\b|\bthan any\b|"
    r"\bworld'?s (?:best|first)\b|\bindia'?s (?:best|first)\b|\bcompared (?:to|with)\b|\boutperforms?\b)",
    re.IGNORECASE,
)


def claim_features(text: str | None) -> list[str]:
    """The absolute, numeric or comparative claim phrases found in `text` (deterministic, English patterns)."""
    if not text:
        return []
    return list(dict.fromkeys(m.group(0).lower() for m in HARD_CLAIM.finditer(text)))


@dataclass(frozen=True)
class ClaimSupport:
    """What the rules need to know about one cited region claim."""

    kind: str
    effective_confidence: str


@dataclass(frozen=True)
class AppliedRule:
    rule: str
    effect: str  # base, +1, cap or block
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "effect": self.effect, "reason": self.reason}


@dataclass
class SeverityDecision:
    severity: Severity
    blocks_go: bool
    confidence: ConfidenceLabel
    rules: list[AppliedRule] = field(default_factory=list)


def topics_fit(category: str, topics: Sequence[str]) -> bool:
    """An ad-code entry fits a category when one of its topics is listed for it ("other" accepts any entry)."""
    allowed = CATEGORY_RULES[category][2]
    return category == "other" or bool(allowed & set(topics))


def supports(claim: ClaimSupport) -> bool:
    return claim.kind in ("observed", "calculated") and claim.effective_confidence in ("moderate", "high")


def decide(
    category: str, *, ad_code_topics: Sequence[Sequence[str]], claims: Sequence[ClaimSupport], quote: str | None,
    deterministic: bool = False,
) -> SeverityDecision:
    """Severity, blocks_go and the evidence-support label for one finding. `ad_code_topics` holds the topic list of each
    cited ad-code entry that exists in the index; entries that do not exist must be removed before calling."""
    base, can_block, _ = CATEGORY_RULES[category]
    level = LEVELS.index(base)
    rules = [AppliedRule("R1_base", "base", f"Base level for {category}: {base}.")]
    if deterministic:
        high = base == "high"
        if high and can_block:
            rules.append(AppliedRule("R7_blocks_go", "block", "A deterministic brand rule is violated."))
        return SeverityDecision(base, high and can_block, "moderate", rules)
    fitting = [t for t in ad_code_topics if topics_fit(category, t)]
    backed = [c for c in claims if supports(c)]
    if fitting:
        level += 1
        rules.append(AppliedRule("R2_ad_code", "+1", f"{len(fitting)} cited ad-code clause(s) fit this category."))
    if backed:
        level += 1
        rules.append(AppliedRule("R3_claim", "+1", f"{len(backed)} observed or calculated region claim(s) at moderate or high confidence."))
    features = claim_features(quote) if category in CLAIM_CATEGORIES else []
    if features:
        level += 1
        rules.append(AppliedRule("R4_hard_claim", "+1", "The quote carries an absolute, numeric or comparative claim: " + ", ".join(features[:3]) + "."))
    if not fitting and not backed and level > 1:
        level = 1
        rules.append(AppliedRule("R5_cap", "cap", "No ad-code clause or supporting claim: capped at medium."))
    level = min(level, 2)
    severity = LEVELS[level]
    blocks = severity == "high" and can_block
    if blocks:
        rules.append(AppliedRule("R7_blocks_go", "block", "High severity in a category that can block a Go verdict."))
    confidence: ConfidenceLabel = "moderate" if fitting and backed else "limited" if fitting or backed else "insufficient"
    return SeverityDecision(severity, blocks, confidence, rules)


# --- deterministic claim-pattern scan (no model): wording that always deserves a human look ----------------------------

PatternSpec = tuple[str, str, re.Pattern[str], tuple[str, ...]]
PATTERNS: tuple[PatternSpec, ...] = (
    ("absolute_guarantee", "unsubstantiated_claim",
     re.compile(r"\b(?:100\s?%\s?(?:guaranteed|safe|effective|natural|pure)|guarantee[ds]?|risk[- ]free|no side effects?)\b", re.IGNORECASE),
     ("asci-1-1", "asci-1-4")),
    ("medical_claim", "health_nutrition_claim",
     re.compile(r"\b(?:cures?|heals?|reverses? (?:ageing|aging|diabetes)|clinically proven|doctor[- ]recommended|miracle)\b", re.IGNORECASE),
     ("asci-1-1", "asci-1-5-d")),
    ("superlative_comparison", "comparative_claim",
     re.compile(r"(?<![a-z])(?:no\.?\s?1|number one|#1)(?![a-z0-9])|\b(?:best in (?:india|class|the world)|better than any|world'?s (?:best|first)|india'?s (?:best|first))\b", re.IGNORECASE),
     ("asci-4-1", "asci-1-1")),
)
PATTERN_TEXT = {
    "absolute_guarantee": "This wording is an absolute guarantee or risk claim. It may need substantiation before it runs.",
    "medical_claim": "This wording makes a health or medical claim. It may need scientific evidence before it runs.",
    "superlative_comparison": "This wording is a superlative or comparative claim. It may need a stated basis and substantiation.",
}


@dataclass(frozen=True)
class PatternHit:
    pattern: str
    category: str
    start: int
    end: int
    ad_code_ids: tuple[str, ...]


def scan_patterns(text: str | None) -> list[PatternHit]:
    if not text:
        return []
    return sorted(
        (PatternHit(pid, cat, m.start(), m.end(), refs) for pid, cat, rx, refs in PATTERNS for m in rx.finditer(text)),
        key=lambda h: (h.start, h.end),
    )
