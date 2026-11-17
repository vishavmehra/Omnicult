"""Scoring version mvp-2 (Omnicult feature 36, Compare and Score). Deterministic code; no model returns a score.

Inputs are typed observations (`app.schemas.launch.VersionObservations`) that other features produce: Quick Read counts
from a synthetic panel, Risk Check findings, code-checked transcreation results, reference grounding and objective checks.
Each dimension is a weighted mean of signals on a 0-100 scale, shaped by the rules below. Every dimension reports its
rule ids, the inputs it used and the inputs it lacked. Same observations and version give the same scores.

mvp-1 (`app.analytics.scoring`, four model-assessed dimensions) is untouched and still scores stored adaptation
evaluations. Mapping from mvp-1: clarity -> message_clarity, cultural_risk -> sensitivity_risk (now computed from findings
instead of a model score), brand_fidelity and cultural_relevance keep their names, objective_consistency is new.

General rules
  A1  A dimension needs its primary input (message_clarity and cultural_relevance: Quick Read; brand_fidelity:
      transcreation checks; sensitivity_risk: Risk Check; objective_consistency: objective checks). Without it the
      dimension is not assessed (null), never defaulted: an unrun Risk Check is not "no risk". Secondary inputs only refine.
  A2  overall = sum(weight * utility) / sum(weight) over the assessed dimensions; utility is the value, or 100 - value
      for sensitivity_risk.
  A3  overall is null when the assessed weight is below 0.5 (too little was assessed to summarise).
Ranking: highest overall first; ties break on lower sensitivity_risk, then request order. A top-two gap under 5 points is
not a meaningful difference. Per-dimension gaps of 10 points or more are listed as major differences.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.schemas import launch as v

SCORING_VERSION: v.ScoringVersion = "mvp-2"
PRIMARY_WEIGHT = 2.0  # an objective marked primary counts double
OBJECTIVE_VALUE = {"met": 1.0, "partly_met": 0.5, "not_met": 0.0}
SEVERITY_POINTS = {"high": 40, "medium": 15, "low": 5}  # sensitivity points per open finding
MIN_COVERAGE = 0.5
MEANINGFUL_MARGIN = 5.0
MAJOR_DIFFERENCE = 10.0
SMALL_PANEL = 10
SCRIPT_ERROR_CAP = 60.0
PROHIBITED_TERM_CAP = 40.0
PRIMARY_OBJECTIVE_MISSED_CAP = 40.0
OPEN_HIGH_FLOOR = 60.0

# dimension -> (label, definition, higher_is_better, weight). Weights sum to 1.
DIMENSIONS: dict[v.ScoreDimension, tuple[str, str, bool, float]] = {
    "message_clarity": (
        "Message clarity", "How well the intended message is understood, and kept through transcreation.", True, 0.25,
    ),
    "brand_fidelity": (
        "Brand fidelity", "Whether protected brand terms survive and prohibited terms stay out.", True, 0.20,
    ),
    "cultural_relevance": (
        "Cultural relevance", "How relevant the language and references are to the region, and how many are evidence-backed.",
        True, 0.25,
    ),
    "sensitivity_risk": (
        "Sensitivity risk", "Open Risk Check findings and regional concerns raised. Higher means more risk.", False, 0.20,
    ),
    "objective_consistency": (
        "Objective consistency", "Whether the creative serves the campaign's stated objectives.", True, 0.10,
    ),
}

# rule id -> (applies to, description). Every id a ScoreCard can carry is listed here (a test enforces it).
RULES: dict[str, tuple[str, str]] = {
    "A1_primary_input_required": ("all", "A dimension without its primary input is not assessed."),
    "A2_overall_weighted_utility": ("overall", "Weighted mean of utilities over the assessed dimensions."),
    "A3_min_coverage": ("overall", f"Overall is null when the assessed weight is below {MIN_COVERAGE}."),
    "M1_quick_read_understanding": (
        "message_clarity", "Share of synthetic respondents who restated the intended message (weight 0.7)."),
    "M2_back_translation": (
        "message_clarity", "Share of lines whose English back-translation kept the meaning (weight 0.3)."),
    "M3_script_error_cap": ("message_clarity", f"Any line with a script error caps the dimension at {SCRIPT_ERROR_CAP:g}."),
    "B1_glossary_compliance": ("brand_fidelity", "Share of lines with no protected-term loss or prohibited term."),
    "B2_prohibited_term_cap": (
        "brand_fidelity", f"Any line with a prohibited term caps the dimension at {PROHIBITED_TERM_CAP:g}."),
    "C1_quick_read_relevance": (
        "cultural_relevance", "Share of synthetic respondents who judged the creative relevant to the region (weight 0.6)."),
    "C2_reference_grounding": (
        "cultural_relevance", "Share of cultural references backed by an evidence claim (weight 0.4)."),
    "R1_open_finding_points": (
        "sensitivity_risk",
        "Open findings score high 40, medium 15, low 5 points, capped at 100 (weight 0.7). Resolved and dismissed "
        "findings score 0."),
    "R2_panel_concerns": (
        "sensitivity_risk", "Share of synthetic respondents who raised a regional concern (weight 0.3)."),
    "R3_open_high_floor": (
        "sensitivity_risk", f"Any open high-severity finding keeps the dimension at {OPEN_HIGH_FLOOR:g} or above."),
    "O1_objective_status": (
        "objective_consistency", "Met 1, partly met 0.5, not met 0; a primary objective counts double."),
    "O2_primary_objective_cap": (
        "objective_consistency", f"A primary objective that is not met caps the dimension at {PRIMARY_OBJECTIVE_MISSED_CAP:g}."),
}

METHODOLOGY = v.ScoringMethodology(
    version=SCORING_VERSION,
    scale="0-100 per dimension",
    dimensions=[
        v.DimensionDoc(dimension=d, label=label, definition=text, higher_is_better=better, weight=weight)
        for d, (label, text, better, weight) in DIMENSIONS.items()
    ],
    rules=[v.RuleDoc(rule_id=rule_id, applies_to=applies, description=text) for rule_id, (applies, text) in RULES.items()],
    aggregation=(
        "overall = sum(weight * utility) / sum(weight) over assessed dimensions; utility = value, or 100 - value for "
        "sensitivity_risk. Weights are fixed in code per scoring version and sum to 1."
    ),
    thresholds={
        "min_coverage": MIN_COVERAGE, "meaningful_margin": MEANINGFUL_MARGIN, "major_difference": MAJOR_DIFFERENCE,
        "small_panel": float(SMALL_PANEL),
    },
    limitations=[
        "Observations may come from a model or a synthetic panel; the score is computed by fixed rules and is not a "
        "prediction of market performance.",
        "Quick Read respondents are synthetic and not independent observations.",
        "A higher overall score does not make one version objectively better; check the comparability notes.",
    ],
)


def pct(part: int | float, whole: int | float) -> float:
    return round(100 * part / whole, 1)


def _signal(name: str, value: float, weight: float, detail: str) -> v.SignalUsed:
    return v.SignalUsed(signal=name, value=round(value, 1), weight=weight, detail=detail)


def _mean(signals: Sequence[v.SignalUsed]) -> float | None:
    total = sum(s.weight for s in signals)
    return sum(s.value * s.weight for s in signals) / total if total else None


@dataclass
class _Draft:
    signals: list[v.SignalUsed] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    value: float | None = None

    def use(self, rule: str, signal: v.SignalUsed) -> None:
        self.signals.append(signal)
        self.rules.append(rule)

    def cap(self, rule: str, ceiling: float, why: str) -> None:
        if self.value is not None and self.value > ceiling:
            self.value = ceiling
            self.rules.append(rule)
            self.notes.append(why)


def _message_clarity(o: v.VersionObservations) -> _Draft:
    d, q, t = _Draft(), o.quick_read, o.transcreation
    if q is None:
        d.missing.append("quick_read")
        d.rules.append("A1_primary_input_required")
        return d
    d.use("M1_quick_read_understanding", _signal(
        "quick_read.understood_share", pct(q.understood, q.respondents), 0.7,
        f"{q.understood} of {q.respondents} synthetic respondents restated the intended message."))
    if t is not None and t.meaning_preserved_lines is not None:
        d.use("M2_back_translation", _signal(
            "transcreation.meaning_preserved_share", pct(t.meaning_preserved_lines, t.lines_checked), 0.3,
            f"{t.meaning_preserved_lines} of {t.lines_checked} lines kept their meaning in back-translation."))
    else:
        d.missing.append("transcreation.back_translation")
    d.value = _mean(d.signals)
    if t is not None and t.script_error_lines:
        d.cap("M3_script_error_cap", SCRIPT_ERROR_CAP, f"{t.script_error_lines} line(s) have a script error.")
    return d


def _brand_fidelity(o: v.VersionObservations) -> _Draft:
    d, t = _Draft(), o.transcreation
    if t is None:
        d.missing.append("transcreation")
        d.rules.append("A1_primary_input_required")
        return d
    clean = t.lines_checked - t.glossary_violation_lines
    d.use("B1_glossary_compliance", _signal(
        "transcreation.glossary_compliance", pct(clean, t.lines_checked), 1.0,
        f"{clean} of {t.lines_checked} lines keep every protected term and avoid prohibited ones."))
    d.value = _mean(d.signals)
    if t.prohibited_term_lines:
        d.cap("B2_prohibited_term_cap", PROHIBITED_TERM_CAP, f"{t.prohibited_term_lines} line(s) contain a prohibited term.")
    return d


def _cultural_relevance(o: v.VersionObservations) -> _Draft:
    d, q, r = _Draft(), o.quick_read, o.references
    if q is None:
        d.missing.append("quick_read")
        d.rules.append("A1_primary_input_required")
        return d
    d.use("C1_quick_read_relevance", _signal(
        "quick_read.relevant_share", pct(q.relevant, q.respondents), 0.6,
        f"{q.relevant} of {q.respondents} synthetic respondents found it relevant to the region."))
    if r is not None:
        d.use("C2_reference_grounding", _signal(
            "references.supported_share", pct(r.references_supported, r.references_checked), 0.4,
            f"{r.references_supported} of {r.references_checked} cultural references are backed by evidence."))
    else:
        d.missing.append("references")
    d.value = _mean(d.signals)
    return d


def open_finding_points(rc: v.RiskCheckObservation) -> int:
    return min(100, sum(SEVERITY_POINTS[f.severity] for f in rc.findings if f.status == "open"))


def _sensitivity_risk(o: v.VersionObservations) -> _Draft:
    d, rc, q = _Draft(), o.risk_check, o.quick_read
    if rc is None:
        d.missing.append("risk_check")
        d.rules.append("A1_primary_input_required")
        return d
    open_findings = [f for f in rc.findings if f.status == "open"]
    d.use("R1_open_finding_points", _signal(
        "risk_check.open_finding_points", open_finding_points(rc), 0.7,
        f"{len(open_findings)} open finding(s) out of {len(rc.findings)} recorded."))
    if q is not None:
        d.use("R2_panel_concerns", _signal(
            "quick_read.concerned_share", pct(q.concerned, q.respondents), 0.3,
            f"{q.concerned} of {q.respondents} synthetic respondents raised a regional concern."))
    else:
        d.missing.append("quick_read")
    d.value = _mean(d.signals)
    if any(f.severity == "high" for f in open_findings) and d.value is not None and d.value < OPEN_HIGH_FLOOR:
        d.value = OPEN_HIGH_FLOOR
        d.rules.append("R3_open_high_floor")
        d.notes.append("An open high-severity finding keeps the risk at or above the floor.")
    return d


def _objective_consistency(o: v.VersionObservations) -> _Draft:
    d = _Draft()
    if not o.objective_checks:
        d.missing.append("objective_checks")
        d.rules.append("A1_primary_input_required")
        return d
    weights = [PRIMARY_WEIGHT if c.primary else 1.0 for c in o.objective_checks]
    value = 100 * sum(w * OBJECTIVE_VALUE[c.status] for w, c in zip(weights, o.objective_checks)) / sum(weights)
    met = sum(c.status == "met" for c in o.objective_checks)
    d.use("O1_objective_status", _signal(
        "objective_checks.weighted_status", value, 1.0, f"{met} of {len(o.objective_checks)} objectives met."))
    d.value = _mean(d.signals)
    if any(c.primary and c.status == "not_met" for c in o.objective_checks):
        d.cap("O2_primary_objective_cap", PRIMARY_OBJECTIVE_MISSED_CAP, "A primary objective is not met.")
    return d


_BUILDERS = {
    "message_clarity": _message_clarity,
    "brand_fidelity": _brand_fidelity,
    "cultural_relevance": _cultural_relevance,
    "sensitivity_risk": _sensitivity_risk,
    "objective_consistency": _objective_consistency,
}


def _explain(label: str, d: _Draft) -> str:
    if d.value is None:
        return f"{label} was not assessed: {', '.join(d.missing)} not supplied."
    text = f"{label} is {round(d.value, 1)} from {len(d.signals)} input(s)."
    return " ".join([text, *d.notes])


def card_limitations(o: v.VersionObservations, cards_coverage: float, unassessed: list[str]) -> list[str]:
    limits = ["Observations may come from a model; the score is computed by fixed rules and is not a prediction of market performance."]
    if (q := o.quick_read) is not None:
        limits.append(
            f"Quick Read results come from a synthetic panel of {q.respondents}; respondents are not real people and "
            "are not independent observations."
        )
        if q.respondents < SMALL_PANEL:
            limits.append(f"The panel is small (n={q.respondents}, under {SMALL_PANEL}); differences are weak evidence.")
    if o.risk_check is not None and not o.risk_check.findings:
        limits.append("The Risk Check recorded no findings; that is not proof that no risk exists, and it is not legal review.")
    if unassessed:
        limits.append(f"Not assessed (no input): {', '.join(unassessed)}. The overall covers {round(cards_coverage * 100)}% of the weight.")
    if o.evidence_meter is None:
        limits.append("No Evidence Meter reading was supplied, so evidence strength for the region is unknown.")
    elif o.evidence_meter.strength != "solid":
        limits.append(f"Evidence Meter reads {o.evidence_meter.strength} for this region; scores rest on thin evidence.")
    return limits


def score_version(version_id: UUID, label: str, o: v.VersionObservations) -> v.ScoreCard:
    """The mvp-2 score card for one version's observations."""
    rows: list[v.DimensionScore] = []
    rule_ids: list[str] = []
    for dimension, (dim_label, _, higher_is_better, weight) in DIMENSIONS.items():
        draft = _BUILDERS[dimension](o)
        value = None if draft.value is None else round(draft.value, 1)
        rows.append(v.DimensionScore(
            dimension=dimension, label=dim_label, value=value, higher_is_better=higher_is_better,
            utility=None if value is None else round(value if higher_is_better else 100 - value, 1), weight=weight,
            rule_ids=draft.rules, inputs_used=draft.signals, missing_inputs=draft.missing,
            explanation=_explain(dim_label, draft),
        ))
        rule_ids += [r for r in draft.rules if r not in rule_ids]
    assessed = [r for r in rows if r.value is not None]
    coverage = round(sum(r.weight for r in assessed), 3)
    overall = None
    if coverage >= MIN_COVERAGE:
        overall = round(sum(r.weight * r.utility for r in assessed) / coverage, 1)  # type: ignore[operator]
        rule_ids.append("A2_overall_weighted_utility")
    else:
        rule_ids.append("A3_min_coverage")
    unassessed = [r.label for r in rows if r.value is None]
    return v.ScoreCard(
        version_id=version_id, label=label, scoring_version=SCORING_VERSION, dimensions=rows, overall=overall,
        coverage=coverage, complete=not unassessed, rule_ids=rule_ids,
        limitations=card_limitations(o, coverage, unassessed), provenance=o.provenance,
    )


# --- comparison -----------------------------------------------------------------------------------


def comparability(cards: Sequence[v.ScoreCard]) -> v.ScoreComparability:
    """Disclose every difference that could explain a score gap other than the creative itself."""
    notes: list[str] = []

    def same(attribute: str, what: str) -> bool:
        values = [getattr(c.provenance, attribute) for c in cards]
        if len(set(values)) <= 1:
            if values[0] is None:
                notes.append(f"The {what} was not recorded for any version.")
            return True
        notes.append(f"The {what} differs between versions ({'; '.join(f'{c.label}: {x or 'not recorded'}' for c, x in zip(cards, values))}).")
        return False

    model, prompt = same("model_id", "model"), same("prompt_version", "prompt version")
    criteria, evidence = same("criteria_version", "evaluation criteria"), same("evidence_snapshot", "evidence")
    assessed = [frozenset(r.dimension for r in c.dimensions if r.value is not None) for c in cards]
    dims = len(set(assessed)) == 1
    if not dims:
        notes.append("Different dimensions were assessed for different versions, so overall scores cover different things.")
    scoring = len({c.scoring_version for c in cards}) == 1
    return v.ScoreComparability(
        same_scoring_version=scoring, same_model=model, same_prompt_version=prompt, same_criteria=criteria,
        same_evidence=evidence, same_dimensions_assessed=dims,
        comparable=all((scoring, model, prompt, criteria, evidence, dims)), notes=notes,
    )


def _risk_of(card: v.ScoreCard) -> float:
    value = next(r.value for r in card.dimensions if r.dimension == "sensitivity_risk")
    return float("inf") if value is None else value


def rank(cards: Sequence[v.ScoreCard]) -> list[v.RankedVersion]:
    order = sorted(
        range(len(cards)),
        key=lambda i: (cards[i].overall is None, -(cards[i].overall or 0.0), _risk_of(cards[i]), i),
    )
    return [
        v.RankedVersion(rank=place, version_id=cards[i].version_id, label=cards[i].label, overall=cards[i].overall)
        for place, i in enumerate(order, start=1)
    ]


def major_differences(cards: Sequence[v.ScoreCard]) -> list[v.DimensionDifference]:
    found: list[v.DimensionDifference] = []
    for index, (dimension, (label, _, higher_is_better, _)) in enumerate(DIMENSIONS.items()):
        values = [(c.version_id, c.dimensions[index].value) for c in cards]
        assessed = [value for _, value in values if value is not None]
        if len(assessed) < 2 or max(assessed) - min(assessed) < MAJOR_DIFFERENCE:
            continue
        best = max(assessed) if higher_is_better else min(assessed)
        found.append(v.DimensionDifference(
            dimension=dimension, label=label, spread=round(max(assessed) - min(assessed), 1),
            leader_version_id=next(vid for vid, value in values if value == best),
            values=[v.VersionValue(version_id=vid, value=value) for vid, value in values],
        ))
    return found


def compare(region_code: str, versions: Sequence[v.ScoreVersionInput]) -> v.ScoreComparison:
    cards = [score_version(x.version_id, x.label, x.observations) for x in versions]
    ranking, comparable = rank(cards), comparability(cards)
    first, second = ranking[0].overall, ranking[1].overall
    margin = first is not None and second is not None and first - second >= MEANINGFUL_MARGIN
    notes = ["Scores combine synthetic-panel and rule-based observations; they do not predict market performance."]
    if not comparable.comparable:
        notes.append("The ranking is shown but is not a like-for-like comparison; read the comparability notes.")
    if not margin:
        notes.append(f"The top two versions are within {MEANINGFUL_MARGIN:g} points or not both scored; treat that as no meaningful difference.")
    return v.ScoreComparison(
        scoring_version=SCORING_VERSION, region_code=region_code, cards=cards, ranking=ranking, meaningful_margin=margin,
        comparability=comparable, major_differences=major_differences(cards), methodology=METHODOLOGY, notes=notes,
    )
