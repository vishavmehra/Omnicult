"""Readiness rules ready-1: one test per rule, the verdict and priority logic, blocks-Go, the evidence cap, determinism."""

from uuid import uuid4

import pytest

from app.analytics import readiness as r
from app.schemas import launch as v
from tests.api.launch_support import (
    conflict, finding, good, meter, objective, quick_read, risk, transcreation,
)


def assess(o: v.VersionObservations) -> v.ReadinessAssessment:
    return r.assess(uuid4(), "A", o)


def fired(a: v.ReadinessAssessment) -> list[str]:
    return [i.rule_id.split("_")[0] for i in a.issues]


# --- the clean case -------------------------------------------------------------------------------


def test_a_clean_version_is_go_and_says_it_is_only_a_recommendation():
    a = assess(good())
    assert (a.verdict, a.rules_applied, a.issues, a.highest_priority_issue) == ("go", ["G0_no_blocking_rule"], [], None)
    assert "8 of 10 synthetic respondents" in a.main_reason and "solid" in a.main_reason
    assert "human approval" in a.next_action and "real people" in a.next_action
    assert any("not an approval" in x for x in a.confidence_limitations)
    assert a.rule_version == "ready-1" and a.scoring_version == "mvp-2" and a.score.overall is not None


def test_partial_evidence_still_allows_go_but_is_disclosed():
    a = assess(good(evidence_meter=meter("partial")))
    assert a.verdict == "go" and "Evidence for the region is partial." in a.confidence_limitations


# --- rethink rules --------------------------------------------------------------------------------


def test_rt1_message_not_understood_means_rethink():
    a = assess(good(quick_read=quick_read(understood=3)))  # 30% < 40%
    assert a.verdict == "rethink" and a.highest_priority_issue.rule_id == "RT1_message_not_understood"
    assert "Only 3 of 10 synthetic respondents" in a.main_reason and "Rework the core message" in a.next_action


def test_rt1_is_not_applied_to_a_panel_that_is_too_small_to_judge():
    a = assess(good(quick_read=quick_read(respondents=4, understood=1, confused=2, positive=1, negative=1, relevant=3, concerned=0)))
    assert a.verdict == "fix" and fired(a) == ["FX15"]  # reported as a small panel instead of over-read
    assert any("share-based rules were not applied" in x for x in a.confidence_limitations)


def test_rt2_a_primary_objective_not_met_means_rethink():
    a = assess(good(objective_checks=[objective("not_met", True)]))
    assert a.verdict == "rethink" and a.highest_priority_issue.rule_id == "RT2_primary_objective_not_met"
    assert "FX9" not in fired(a)  # the gap is not reported twice


def test_rt3_severe_unresolved_risk_means_rethink():
    a = assess(good(risk_check=risk(finding("h1", "high"), finding("h2", "high"))))  # 80 points
    assert a.verdict == "rethink" and "RT3" in fired(a) and "FX2" in fired(a)
    assert a.highest_priority_issue.rule_id == "RT3_severe_unresolved_risk"


def test_rt3_ignores_resolved_findings():
    a = assess(good(risk_check=risk(finding("h1", "high"), finding("h2", "high", status="resolved"))))
    assert a.verdict == "fix" and fired(a) == ["FX2"]


def test_rt4_a_region_relevance_failure_means_rethink():
    a = assess(good(quick_read=quick_read(relevant=2)))
    assert a.verdict == "rethink" and a.highest_priority_issue.rule_id == "RT4_region_relevance_failure"


# --- blocks-Go ------------------------------------------------------------------------------------


def test_an_unresolved_blocks_go_finding_means_not_go_even_when_it_is_only_low_severity():
    a = assess(good(risk_check=risk(finding("b1", "low", blocks_go=True, claims=[uuid4()]))))
    assert a.verdict == "fix" and a.highest_priority_issue.rule_id == "FX1_blocking_finding_unresolved"
    assert a.risk.blocking == 1 and "b1" in a.main_reason and "Finding b1" in a.next_action


@pytest.mark.parametrize("status", ["resolved", "dismissed"])
def test_a_resolved_or_dismissed_blocking_finding_no_longer_blocks_go(status):
    assert assess(good(risk_check=risk(finding("b1", "high", status=status, blocks_go=True)))).verdict == "go"


def test_fx2_one_open_high_finding_is_fix_not_rethink():
    a = assess(good(risk_check=risk(finding("h1", "high"))))
    assert a.verdict == "fix" and fired(a) == ["FX2"] and a.risk.open_high == 1


def test_fx10_three_open_medium_findings_are_fix_but_two_are_not():
    assert assess(good(risk_check=risk(finding("m1"), finding("m2")))).verdict == "go"
    a = assess(good(risk_check=risk(finding("m1"), finding("m2"), finding("m3"))))
    assert a.verdict == "fix" and fired(a) == ["FX10"]


def test_open_low_and_medium_findings_that_do_not_block_are_disclosed():
    a = assess(good(risk_check=risk(finding("m1"), finding("l1", "low"))))
    assert a.verdict == "go" and any("2 open low or medium finding(s) remain" in x for x in a.confidence_limitations)


# --- conflicts ------------------------------------------------------------------------------------


def test_fx3_an_open_conflict_on_a_relied_on_claim_means_at_most_fix():
    claim = uuid4()
    a = assess(good(open_conflicts=[conflict(True, "open", [claim])]))
    assert a.verdict == "fix" and a.highest_priority_issue.rule_id == "FX3_conflict_on_relied_claim"
    assert claim in a.supporting_evidence_ids and len(a.open_conflicts) == 1
    assert "Ask a reviewer to resolve the conflict" in a.next_action


def test_a_conflict_awaiting_review_still_counts_as_open():
    assert assess(good(open_conflicts=[conflict(True, "review_requested")])).verdict == "fix"


def test_a_conflict_the_creative_does_not_rely_on_is_a_limitation_only():
    a = assess(good(open_conflicts=[conflict(False)]))
    assert a.verdict == "go" and len(a.open_conflicts) == 1
    assert any("not on claims this creative relies on" in x for x in a.confidence_limitations)


def test_a_resolved_conflict_is_ignored():
    a = assess(good(open_conflicts=[conflict(True, "resolved")]))
    assert a.verdict == "go" and a.open_conflicts == []


# --- brand, language, message, relevance, objectives ------------------------------------------------


def test_fx4_brand_glossary_violations_are_fix():
    a = assess(good(transcreation=transcreation(glossary_violation_lines=1, prohibited_term_lines=1)))
    assert a.verdict == "fix" and fired(a) == ["FX4"] and "1 with a prohibited term" in a.main_reason


def test_fx5_script_errors_are_fix():
    a = assess(good(transcreation=transcreation(script_error_lines=2)))
    assert a.verdict == "fix" and fired(a) == ["FX5"]


def test_fx6_a_partly_understood_message_is_fix():
    a = assess(good(quick_read=quick_read(understood=5)))  # 50%: not a failure, not good enough
    assert a.verdict == "fix" and fired(a) == ["FX6"]
    assert assess(good(quick_read=quick_read(understood=7))).verdict == "go"  # 70% clears the bar


def test_fx7_back_translation_drift_is_fix():
    a = assess(good(transcreation=transcreation(meaning_preserved_lines=7)))
    assert a.verdict == "fix" and fired(a) == ["FX7"]
    assert assess(good(transcreation=transcreation(meaning_preserved_lines=None))).verdict == "go"  # not checked is not drift


def test_fx8_weak_relevance_is_fix():
    a = assess(good(quick_read=quick_read(relevant=4)))
    assert a.verdict == "fix" and fired(a) == ["FX8"]


def test_fx9_an_objective_gap_is_fix():
    a = assess(good(objective_checks=[objective("partly_met", False)]))
    assert a.verdict == "fix" and fired(a) == ["FX9"]


# --- evidence cap and missing inputs --------------------------------------------------------------


def test_fx11_thin_evidence_caps_an_otherwise_perfect_version_at_fix():
    a = assess(good(evidence_meter=meter("weak")))
    assert a.verdict == "fix" and fired(a) == ["FX11"] and a.evidence_strength == "weak"
    assert "Evidence for the region is weak." in a.confidence_limitations
    assert "Add independent sources" in a.next_action


def test_fx12_unknown_evidence_strength_is_fix():
    a = assess(good(evidence_meter=None))
    assert a.verdict == "fix" and fired(a) == ["FX12"] and a.evidence_strength is None


def test_fx13_and_fx14_missing_quick_read_and_risk_check_are_fix():
    a = assess(good(quick_read=None, risk_check=None))
    assert a.verdict == "fix" and {"FX13", "FX14"} <= set(fired(a))
    assert assess(good(quick_read=None)).highest_priority_issue.rule_id == "FX13_no_quick_read"


def test_nothing_supplied_is_fix_and_never_go():
    a = assess(v.VersionObservations())
    assert a.verdict == "fix" and {"FX12", "FX13", "FX14"} <= set(fired(a)) and a.score.overall is None


def test_fx16_a_low_overall_score_is_fix():
    # every share-based rule passes, but several small weaknesses add up: clarity 73, relevance 30, risk 65 -> overall 62.75
    minor = risk(finding("m1"), finding("m2"), *[finding(f"l{i}", "low") for i in range(4)])
    o = good(quick_read=quick_read(understood=7, relevant=5, concerned=10), risk_check=minor, references=v.ReferenceObservation(
        references_checked=4, references_supported=0), transcreation=transcreation(meaning_preserved_lines=8))
    a = assess(o)
    assert a.verdict == "fix" and fired(a) == ["FX16"] and a.score.overall < r.GO_MIN_OVERALL


# --- ordering, priority, evidence ------------------------------------------------------------------


def test_rethink_outranks_fix_and_the_highest_priority_issue_is_the_lowest_number():
    a = assess(good(quick_read=quick_read(understood=2), transcreation=transcreation(script_error_lines=1),
                    evidence_meter=meter("weak")))
    assert a.verdict == "rethink"
    assert [i.priority for i in a.issues] == sorted(i.priority for i in a.issues)
    assert a.highest_priority_issue == a.issues[0] and a.issues[0].rule_id == "RT1_message_not_understood"
    assert "more issue(s) are listed" in a.main_reason
    assert a.rules_applied == [i.rule_id for i in a.issues]


def test_supporting_evidence_ids_are_unique_and_come_from_the_inputs():
    shared, only_finding, only_conflict, panel = uuid4(), uuid4(), uuid4(), uuid4()
    a = assess(good(
        quick_read=quick_read(evidence_ids=[panel]),
        risk_check=risk(finding("h1", "high", claims=[shared, only_finding])),
        open_conflicts=[conflict(True, "open", [shared, only_conflict])],
    ))
    assert sorted(a.supporting_evidence_ids) == sorted({shared, only_finding, only_conflict, panel})
    assert len(a.supporting_evidence_ids) == 4
    issue = next(i for i in a.issues if i.rule_id == "FX2_open_high_finding")
    assert set(issue.evidence_ids) == {shared, only_finding}


# --- determinism and documentation ------------------------------------------------------------------


def test_same_inputs_and_rule_version_give_the_same_verdict():
    o, version_id = good(risk_check=risk(finding("h1", "high"), finding("m1")), open_conflicts=[conflict()]), uuid4()
    first, second = r.assess(version_id, "A", o), r.assess(version_id, "A", o.model_copy(deep=True))
    assert first.model_dump() == second.model_dump()


def test_every_rule_is_unique_documented_and_ordered_by_effect():
    ids = [x.rule_id for x in r.RULES]
    assert len(ids) == len(set(ids)) == 20
    assert len({x.priority for x in r.RULES}) == 20
    docs = r.RULES_DOC
    assert [x.rule_id for x in docs.rules] == ids and docs.rule_version == "ready-1"
    assert all(x.priority < 20 for x in r.RULES if x.effect == "rethink")
    assert all(x.priority >= 20 for x in r.RULES if x.effect == "fix")
    assert set(docs.verdict_meanings) == {"go", "fix", "rethink"}
    assert all(x.description for x in docs.rules) and docs.thresholds["min_panel"] == r.MIN_PANEL


def test_every_issue_a_verdict_can_carry_is_a_documented_rule():
    cases = [
        good(quick_read=quick_read(understood=2), risk_check=risk(finding("a", "high"), finding("b", "high"), finding("c", blocks_go=True)),
             transcreation=transcreation(glossary_violation_lines=1, script_error_lines=1, meaning_preserved_lines=1),
             objective_checks=[objective("not_met")], evidence_meter=meter("weak"), open_conflicts=[conflict()]),
        v.VersionObservations(),
    ]
    documented = {x.rule_id for x in r.RULES}
    for o in cases:
        assert {i.rule_id for i in assess(o).issues} <= documented
