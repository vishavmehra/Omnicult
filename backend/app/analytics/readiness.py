"""Readiness Board rules, version ready-1 (Omnicult feature 37). Deterministic code; no model chooses a verdict.

A verdict is computed per region and creative version from typed observations (Quick Read counts, Risk Check findings,
transcreation checks, the Evidence Meter, evidence conflicts, objective checks) and the mvp-2 score.

    rethink  the creative's core is not working in this region: change the idea, not the wording.
    fix      specific, nameable problems stand between this version and Go, or too little is known to say Go.
    go       no rule below fires. A recommendation to seek human approval, never an approval and never a forecast.

Every rule that fires is reported with its id, a summary, an action and the evidence it read. The verdict is the worst
effect among them; the highest-priority issue is the lowest priority number. The rules are listed in RULES, which is
also served as documentation, and every threshold is a named constant below.

Rule summary (see RULES for the exact text):
  rethink   RT1 message not understood, RT2 primary objective not met, RT3 severe unresolved risk, RT4 region relevance failure
  fix       FX1 a finding that blocks Go is unresolved, FX2 open high-severity finding, FX3 open conflict on a claim the
            creative relies on, FX4 brand-term violation, FX5 script error, FX6 message only partly understood, FX7
            back-translation drift, FX8 weak relevance, FX9 objective gap, FX10 several open medium findings, FX11 thin
            evidence (Evidence Meter weak: caps at fix), FX12 evidence strength unknown, FX13 no Quick Read, FX14 no Risk
            Check, FX15 panel too small, FX16 overall score below the Go threshold
Share-based rules (RT1, RT4, FX6, FX8) apply only to a panel of MIN_PANEL or more respondents; a smaller panel is
reported by FX15 instead of being over-read.
"""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.analytics import scoring_v2
from app.schemas import launch as v

RULE_VERSION = "ready-1"
MIN_PANEL = 5
MESSAGE_FAIL_SHARE = 0.40  # understood share below this: rethink
MESSAGE_GO_SHARE = 0.65  # below this: fix
RELEVANCE_FAIL_SHARE = 0.30
RELEVANCE_GO_SHARE = 0.50
SEVERE_RISK_POINTS = 80  # open-finding points (high 40, medium 15, low 5)
MEDIUM_FINDINGS_FIX = 3
BACK_TRANSLATION_GO_SHARE = 0.80
OBJECTIVE_GO_VALUE = 60.0
GO_MIN_OVERALL = 65.0

VERDICT_MEANINGS = {
    "go": "No readiness rule fires. A recommendation to seek human approval; not an approval and not a forecast.",
    "fix": "Specific problems stand between this version and Go, or too little is known to say Go.",
    "rethink": "The creative's core is not working in this region: change the idea, not the wording.",
}


@dataclass(frozen=True)
class Hit:
    summary: str
    action: str
    source: str
    evidence_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class Context:
    o: v.VersionObservations
    card: v.ScoreCard

    @property
    def panel(self) -> v.QuickReadObservation | None:
        q = self.o.quick_read
        return q if q is not None and q.respondents >= MIN_PANEL else None

    @property
    def open_findings(self) -> list[v.RiskFindingInput]:
        return [f for f in (self.o.risk_check.findings if self.o.risk_check else []) if f.status == "open"]

    @property
    def unresolved_conflicts(self) -> list[v.OpenConflictInput]:
        return [c for c in self.o.open_conflicts if c.status != "resolved"]

    def dimension(self, name: str) -> float | None:
        return next(d.value for d in self.card.dimensions if d.dimension == name)


def _ids(*groups: list[UUID]) -> tuple[UUID, ...]:
    return tuple(dict.fromkeys(i for group in groups for i in group))


def _names(findings: list[v.RiskFindingInput], limit: int = 3) -> str:
    shown = ", ".join(f.id for f in findings[:limit])
    return shown + (f" and {len(findings) - limit} more" if len(findings) > limit else "")


# --- rules: each returns a Hit when it fires ----------------------------------------------------


def _rt1(c: Context) -> Hit | None:
    q = c.panel
    if q is None or q.understood / q.respondents >= MESSAGE_FAIL_SHARE:
        return None
    return Hit(
        f"Only {q.understood} of {q.respondents} synthetic respondents restated the intended message.",
        "Rework the core message for this region, then run Quick Read again.", "quick_read", _ids(q.evidence_ids),
    )


def _rt2(c: Context) -> Hit | None:
    missed = [x for x in c.o.objective_checks if x.primary and x.status == "not_met"]
    if not missed:
        return None
    return Hit(
        f"The primary objective is not met: {missed[0].statement}",
        "Rethink the creative so it serves the primary objective before any further edits.", "objective_checks",
    )


def _rt3(c: Context) -> Hit | None:
    if c.o.risk_check is None or scoring_v2.open_finding_points(c.o.risk_check) < SEVERE_RISK_POINTS:
        return None
    findings = c.open_findings
    return Hit(
        f"Unresolved risk is too extensive to patch ({len(findings)} open findings: {_names(findings)}).",
        "Rethink the concept: resolve the high-severity findings at their source rather than editing around them.",
        "risk_check", _ids(*[f.claim_ids for f in findings]),
    )


def _rt4(c: Context) -> Hit | None:
    q = c.panel
    if q is None or q.relevant / q.respondents >= RELEVANCE_FAIL_SHARE:
        return None
    return Hit(
        f"Only {q.relevant} of {q.respondents} synthetic respondents found it relevant to this region.",
        "Rethink the references and language for this region; consider a different cultural anchor.", "quick_read",
        _ids(q.evidence_ids),
    )


def _fx1(c: Context) -> Hit | None:
    blocking = [f for f in c.open_findings if f.blocks_go]
    if not blocking:
        return None
    return Hit(
        f"{len(blocking)} unresolved finding(s) rule out Go: {_names(blocking)}.",
        f"Resolve or formally dismiss finding {blocking[0].id} ({blocking[0].summary}), then recompute.", "risk_check",
        _ids(*[f.claim_ids for f in blocking]),
    )


def _fx2(c: Context) -> Hit | None:
    high = [f for f in c.open_findings if f.severity == "high"]
    if not high:
        return None
    return Hit(
        f"{len(high)} open high-severity finding(s): {_names(high)}.",
        f"Fix the high-severity finding {high[0].id} ({high[0].summary}) and re-run Risk Check.", "risk_check",
        _ids(*[f.claim_ids for f in high]),
    )


def _fx3(c: Context) -> Hit | None:
    relied = [x for x in c.unresolved_conflicts if x.relied_on]
    if not relied:
        return None
    return Hit(
        f"{len(relied)} open evidence conflict(s) concern claims this creative relies on.",
        f"Ask a reviewer to resolve the conflict: {relied[0].summary}", "open_conflicts",
        _ids(*[x.claim_ids for x in relied]),
    )


def _fx4(c: Context) -> Hit | None:
    t = c.o.transcreation
    if t is None or not t.glossary_violation_lines:
        return None
    prohibited = f", {t.prohibited_term_lines} with a prohibited term" if t.prohibited_term_lines else ""
    return Hit(
        f"{t.glossary_violation_lines} of {t.lines_checked} lines break the Brand Glossary{prohibited}.",
        "Restore the protected terms and remove prohibited ones, then re-run the glossary check.", "transcreation",
    )


def _fx5(c: Context) -> Hit | None:
    t = c.o.transcreation
    if t is None or not t.script_error_lines:
        return None
    return Hit(
        f"{t.script_error_lines} line(s) have a script error.",
        "Correct the script in those lines and have a native speaker check the rendering.", "transcreation",
    )


def _fx6(c: Context) -> Hit | None:
    q = c.panel
    if q is None:
        return None
    share = q.understood / q.respondents
    if share < MESSAGE_FAIL_SHARE or share >= MESSAGE_GO_SHARE:
        return None
    return Hit(
        f"The message was understood by {q.understood} of {q.respondents} synthetic respondents (Go needs {MESSAGE_GO_SHARE:.0%}).",
        "Clarify the headline or call to action and run Quick Read again.", "quick_read", _ids(q.evidence_ids),
    )


def _fx7(c: Context) -> Hit | None:
    t = c.o.transcreation
    if t is None or t.meaning_preserved_lines is None or t.meaning_preserved_lines / t.lines_checked >= BACK_TRANSLATION_GO_SHARE:
        return None
    return Hit(
        f"Only {t.meaning_preserved_lines} of {t.lines_checked} lines kept their meaning in back-translation.",
        "Review the lines whose back-translation drifts and adjust the regional copy.", "transcreation",
    )


def _fx8(c: Context) -> Hit | None:
    q = c.panel
    if q is None:
        return None
    share = q.relevant / q.respondents
    if share < RELEVANCE_FAIL_SHARE or share >= RELEVANCE_GO_SHARE:
        return None
    return Hit(
        f"Only {q.relevant} of {q.respondents} synthetic respondents found it relevant to this region (Go needs {RELEVANCE_GO_SHARE:.0%}).",
        "Strengthen regional references using supported evidence claims.", "quick_read", _ids(q.evidence_ids),
    )


def _fx9(c: Context) -> Hit | None:
    value = c.dimension("objective_consistency")
    if value is None or value >= OBJECTIVE_GO_VALUE or any(x.primary and x.status == "not_met" for x in c.o.objective_checks):
        return None
    gaps = [x for x in c.o.objective_checks if x.status != "met"]
    return Hit(
        f"Objective consistency is {value:g}; {len(gaps)} objective(s) are not fully met (first: {gaps[0].statement}).",
        "Adjust the creative toward the unmet objectives.", "objective_checks",
    )


def _fx10(c: Context) -> Hit | None:
    medium = [f for f in c.open_findings if f.severity == "medium"]
    if len(medium) < MEDIUM_FINDINGS_FIX:
        return None
    return Hit(
        f"{len(medium)} open medium-severity findings: {_names(medium)}.",
        "Work through the medium findings, starting with " + medium[0].id + ".", "risk_check",
        _ids(*[f.claim_ids for f in medium]),
    )


def _fx11(c: Context) -> Hit | None:
    meter = c.o.evidence_meter
    if meter is None or meter.strength != "weak":
        return None
    return Hit(
        f"Evidence for this region is weak ({meter.supported_claims} supported of {meter.claims} claims); Go is not available.",
        "Add independent sources for this region in Market Lens, then recompute.", "evidence_meter",
    )


def _fx12(c: Context) -> Hit | None:
    if c.o.evidence_meter is not None:
        return None
    return Hit(
        "Evidence strength for this region is unknown: no Evidence Meter reading was supplied.",
        "Open the region's Evidence Meter and include its reading, then recompute.", "evidence_meter",
    )


def _fx13(c: Context) -> Hit | None:
    if c.o.quick_read is not None:
        return None
    return Hit("No Quick Read has been run for this version and region.", "Run Quick Read for this region.", "quick_read")


def _fx14(c: Context) -> Hit | None:
    if c.o.risk_check is not None:
        return None
    return Hit("No Risk Check has been run for this version and region.", "Run Risk Check for this region.", "risk_check")


def _fx15(c: Context) -> Hit | None:
    q = c.o.quick_read
    if q is None or q.respondents >= MIN_PANEL:
        return None
    return Hit(
        f"The Quick Read panel is too small to judge ({q.respondents} respondents; at least {MIN_PANEL} needed).",
        "Re-run Quick Read with a larger synthetic panel.", "quick_read", _ids(q.evidence_ids),
    )


def _fx16(c: Context) -> Hit | None:
    overall = c.card.overall
    if overall is None or overall >= GO_MIN_OVERALL:
        return None
    return Hit(
        f"The overall mvp-2 score is {overall:g}; Go needs {GO_MIN_OVERALL:g}.",
        "Improve the weakest dimension in the score card, then compare versions again.", "score",
    )


@dataclass(frozen=True)
class Rule:
    rule_id: str
    effect: str  # "fix" or "rethink"
    priority: int
    description: str
    check: Callable[[Context], Hit | None]


RULES: tuple[Rule, ...] = (
    Rule("RT1_message_not_understood", "rethink", 10,
         f"At least {MIN_PANEL} synthetic respondents and fewer than {MESSAGE_FAIL_SHARE:.0%} restated the intended message.", _rt1),
    Rule("RT2_primary_objective_not_met", "rethink", 11, "A primary objective is marked not met.", _rt2),
    Rule("RT3_severe_unresolved_risk", "rethink", 12,
         f"Open Risk Check findings total {SEVERE_RISK_POINTS} points or more (high 40, medium 15, low 5).", _rt3),
    Rule("RT4_region_relevance_failure", "rethink", 13,
         f"At least {MIN_PANEL} synthetic respondents and fewer than {RELEVANCE_FAIL_SHARE:.0%} found it relevant to the region.", _rt4),
    Rule("FX1_blocking_finding_unresolved", "fix", 20, "A finding flagged blocks-Go is still open.", _fx1),
    Rule("FX2_open_high_finding", "fix", 21, "A high-severity Risk Check finding is still open.", _fx2),
    Rule("FX3_conflict_on_relied_claim", "fix", 22,
         "An unresolved evidence conflict concerns a claim the creative relies on: at most fix.", _fx3),
    Rule("FX4_brand_term_violation", "fix", 23, "A line loses a protected term or contains a prohibited term.", _fx4),
    Rule("FX5_script_error", "fix", 24, "A regional-language line has a script error.", _fx5),
    Rule("FX6_message_partly_understood", "fix", 25,
         f"Understood share is at least {MESSAGE_FAIL_SHARE:.0%} but under {MESSAGE_GO_SHARE:.0%} (panel of {MIN_PANEL}+).", _fx6),
    Rule("FX7_back_translation_drift", "fix", 26,
         f"Fewer than {BACK_TRANSLATION_GO_SHARE:.0%} of lines kept their meaning in back-translation.", _fx7),
    Rule("FX8_weak_relevance", "fix", 27,
         f"Relevant share is at least {RELEVANCE_FAIL_SHARE:.0%} but under {RELEVANCE_GO_SHARE:.0%} (panel of {MIN_PANEL}+).", _fx8),
    Rule("FX9_objective_gap", "fix", 28, f"Objective consistency is under {OBJECTIVE_GO_VALUE:g}.", _fx9),
    Rule("FX10_open_medium_findings", "fix", 29, f"{MEDIUM_FINDINGS_FIX} or more open medium-severity findings.", _fx10),
    Rule("FX11_thin_evidence", "fix", 30, "The Evidence Meter reads weak for the region: caps at fix.", _fx11),
    Rule("FX12_evidence_unknown", "fix", 31, "No Evidence Meter reading was supplied: strength is unknown, caps at fix.", _fx12),
    Rule("FX13_no_quick_read", "fix", 32, "No Quick Read result was supplied.", _fx13),
    Rule("FX14_no_risk_check", "fix", 33, "No Risk Check result was supplied.", _fx14),
    Rule("FX15_panel_too_small", "fix", 34, f"The Quick Read panel has fewer than {MIN_PANEL} respondents.", _fx15),
    Rule("FX16_score_below_go", "fix", 35, f"The overall mvp-2 score is under {GO_MIN_OVERALL:g}.", _fx16),
)

GO_RULE = "G0_no_blocking_rule"

RULES_DOC = v.ReadinessRules(
    rule_version=RULE_VERSION,
    scoring_version=scoring_v2.SCORING_VERSION,
    verdict_meanings=VERDICT_MEANINGS,
    rules=[v.ReadinessRuleDoc(rule_id=r.rule_id, effect=r.effect, priority=r.priority, description=r.description) for r in RULES],  # type: ignore[arg-type]
    thresholds={
        "min_panel": MIN_PANEL, "message_fail_share": MESSAGE_FAIL_SHARE, "message_go_share": MESSAGE_GO_SHARE,
        "relevance_fail_share": RELEVANCE_FAIL_SHARE, "relevance_go_share": RELEVANCE_GO_SHARE,
        "severe_risk_points": SEVERE_RISK_POINTS, "medium_findings_fix": MEDIUM_FINDINGS_FIX,
        "back_translation_go_share": BACK_TRANSLATION_GO_SHARE, "objective_go_value": OBJECTIVE_GO_VALUE,
        "go_min_overall": GO_MIN_OVERALL,
    },
    notes=[
        "The verdict is the worst effect among the rules that fire; with none firing it is go (G0_no_blocking_rule).",
        "The highest-priority issue is the fired rule with the lowest priority number.",
        "Go is a recommendation to seek human approval. Approvals are recorded separately and only by people.",
        "Quick Read inputs are synthetic and are never treated as real consumer evidence.",
    ],
)


# --- assessment ---------------------------------------------------------------------------------


def _limitations(c: Context, verdict: str) -> list[str]:
    o, out = c.o, []
    if (q := o.quick_read) is not None:
        out.append(f"Quick Read is a synthetic panel of {q.respondents}; its respondents are not real people and not independent observations.")
        if q.respondents < MIN_PANEL:
            out.append(f"The panel is under {MIN_PANEL} respondents; share-based rules were not applied.")
    if (m := o.evidence_meter) is None:
        out.append("Evidence strength for the region is unknown (no Evidence Meter reading).")
    else:
        if m.strength != "solid":
            out.append(f"Evidence for the region is {m.strength}.")
        if m.stale_claims:
            out.append(f"{m.stale_claims} claim(s) behind the region's evidence are stale.")
    if (unrelated := [x for x in c.unresolved_conflicts if not x.relied_on]):
        out.append(f"{len(unrelated)} open evidence conflict(s) exist in the region but not on claims this creative relies on.")
    if o.risk_check is not None:
        out.append("Risk Check findings are model and rule observations that need human review; it is not legal review.")
        if not o.risk_check.findings:
            out.append("The Risk Check recorded no findings; that is not proof that no risk exists.")
        if (rest := [f for f in c.open_findings if f.severity != "high" and not f.blocks_go]):
            out.append(f"{len(rest)} open low or medium finding(s) remain and do not block this verdict.")
    if o.transcreation is None:
        out.append("No Brand Glossary or back-translation check was supplied.")
    if verdict == "go":
        out.append("Go is a recommendation computed from these inputs, not an approval and not a forecast of results.")
    return out


def assess(version_id: UUID, label: str, o: v.VersionObservations) -> v.ReadinessAssessment:
    """The readiness verdict for one version in one region. Pure: the same observations always give the same result."""
    card = scoring_v2.score_version(version_id, label, o)
    c = Context(o, card)
    fired = [(rule, hit) for rule in RULES if (hit := rule.check(c)) is not None]
    issues = sorted(
        (
            v.ReadinessIssue(
                rule_id=rule.rule_id, priority=rule.priority, effect=rule.effect,  # type: ignore[arg-type]
                summary=hit.summary, action=hit.action, source=hit.source, evidence_ids=list(hit.evidence_ids),
            )
            for rule, hit in fired
        ),
        key=lambda issue: issue.priority,
    )
    verdict = "rethink" if any(i.effect == "rethink" for i in issues) else "fix" if issues else "go"
    top = issues[0] if issues else None
    if top is not None:
        more = f" ({len(issues) - 1} more issue(s) are listed.)" if len(issues) > 1 else ""
        reason, action = top.summary + more, top.action
    else:
        q, meter = o.quick_read, o.evidence_meter
        assert q is not None and meter is not None  # FX12 and FX13 fire without them
        reason = (
            f"No readiness rule fires: {q.understood} of {q.respondents} synthetic respondents understood the message, "
            f"no unresolved finding blocks Go, and evidence for the region reads {meter.strength}."
        )
        action = "Send this version for human approval in this region, and validate with real people before committing launch spend."
    findings = o.risk_check.findings if o.risk_check else []
    open_findings = c.open_findings
    evidence = _ids(
        list(o.quick_read.evidence_ids) if o.quick_read else [], *[f.claim_ids for f in findings],
        *[x.claim_ids for x in c.unresolved_conflicts], *[i.evidence_ids for i in issues],
    )
    return v.ReadinessAssessment(
        verdict=verdict, main_reason=reason, highest_priority_issue=top, issues=issues, next_action=action,  # type: ignore[arg-type]
        supporting_evidence_ids=list(evidence), open_conflicts=c.unresolved_conflicts,
        confidence_limitations=_limitations(c, verdict),
        risk=v.RiskSummary(
            open_high=sum(f.severity == "high" for f in open_findings), open_medium=sum(f.severity == "medium" for f in open_findings),
            open_low=sum(f.severity == "low" for f in open_findings), blocking=sum(f.blocks_go for f in open_findings),
        ),
        evidence_strength=o.evidence_meter.strength if o.evidence_meter else None, score=card, rule_version=RULE_VERSION,
        scoring_version=scoring_v2.SCORING_VERSION,
        rules_applied=[i.rule_id for i in issues] or [GO_RULE], provenance=o.provenance,
    )
