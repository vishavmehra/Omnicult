"""Scoring version mvp-2: each rule, the aggregation, determinism, comparability disclosure, ranking, and that mvp-1 still works."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.analytics import SCORING_VERSION as MVP1
from app.analytics import scoring_v2 as s2
from app.schemas import launch as v
from tests.api.launch_support import finding, good, meter, objective, quick_read, risk, transcreation


def card(o: v.VersionObservations, label: str = "A") -> v.ScoreCard:
    return s2.score_version(uuid4(), label, o)


def dim(c: v.ScoreCard, name: str) -> v.DimensionScore:
    return next(d for d in c.dimensions if d.dimension == name)


def version(label: str, o: v.VersionObservations) -> v.ScoreVersionInput:
    return v.ScoreVersionInput(version_id=uuid4(), label=label, observations=o)


# --- definition -----------------------------------------------------------------------------------


def test_weights_sum_to_one_and_the_methodology_documents_every_dimension_and_rule():
    assert sum(w for *_, w in s2.DIMENSIONS.values()) == pytest.approx(1.0)
    assert [d.dimension for d in s2.METHODOLOGY.dimensions] == list(s2.DIMENSIONS)
    assert {r.rule_id for r in s2.METHODOLOGY.rules} == set(s2.RULES)
    assert s2.METHODOLOGY.version == "mvp-2" and MVP1 == "mvp-1"  # mvp-1 stays for stored evaluations


def test_the_five_required_dimensions_exist():
    assert list(s2.DIMENSIONS) == [
        "message_clarity", "brand_fidelity", "cultural_relevance", "sensitivity_risk", "objective_consistency"
    ]
    assert s2.DIMENSIONS["sensitivity_risk"][2] is False  # higher means more risk


# --- one test per rule ----------------------------------------------------------------------------


def test_m1_and_m2_weight_the_panel_and_the_back_translation():
    d = dim(card(good()), "message_clarity")  # 8/10 understood = 80, 9/10 meaning kept = 90
    assert d.value == 83.0 and d.rule_ids == ["M1_quick_read_understanding", "M2_back_translation"]
    assert [(x.signal, x.value, x.weight) for x in d.inputs_used] == [
        ("quick_read.understood_share", 80.0, 0.7), ("transcreation.meaning_preserved_share", 90.0, 0.3)
    ]
    only_panel = dim(card(good(transcreation=transcreation(meaning_preserved_lines=None))), "message_clarity")
    assert only_panel.value == 80.0 and only_panel.missing_inputs == ["transcreation.back_translation"]


def test_m3_a_script_error_caps_clarity():
    d = dim(card(good(transcreation=transcreation(script_error_lines=1))), "message_clarity")
    assert d.value == s2.SCRIPT_ERROR_CAP and "M3_script_error_cap" in d.rule_ids and "script error" in d.explanation


def test_b1_glossary_compliance_and_b2_prohibited_term_cap():
    b1 = dim(card(good(transcreation=transcreation(glossary_violation_lines=2))), "brand_fidelity")
    assert b1.value == 80.0 and b1.rule_ids == ["B1_glossary_compliance"]
    b2 = dim(card(good(transcreation=transcreation(glossary_violation_lines=1, prohibited_term_lines=1))), "brand_fidelity")
    assert b2.value == s2.PROHIBITED_TERM_CAP and b2.rule_ids == ["B1_glossary_compliance", "B2_prohibited_term_cap"]


def test_c1_and_c2_relevance_blends_the_panel_with_evidence_grounding():
    d = dim(card(good()), "cultural_relevance")  # 70 * 0.6 + 75 * 0.4
    assert d.value == 72.0 and d.rule_ids == ["C1_quick_read_relevance", "C2_reference_grounding"]
    no_refs = dim(card(good(references=None)), "cultural_relevance")
    assert no_refs.value == 70.0 and no_refs.missing_inputs == ["references"]


def test_r1_and_r2_risk_counts_only_open_findings_and_panel_concerns():
    findings = risk(finding("a", "medium"), finding("b", "medium"), finding("c", "low", status="resolved"),
                    finding("d", "high", status="dismissed"))
    d = dim(card(good(risk_check=findings)), "sensitivity_risk")  # 30 open points * 0.7 + 10% concerned * 0.3
    assert d.value == 24.0 and d.rule_ids == ["R1_open_finding_points", "R2_panel_concerns"]
    assert d.inputs_used[0].detail == "2 open finding(s) out of 4 recorded."


def test_r1_points_are_capped_at_100():
    many = risk(*[finding(f"h{i}", "high") for i in range(5)])
    assert dim(card(good(risk_check=many)), "sensitivity_risk").inputs_used[0].value == 100.0


def test_r3_an_open_high_finding_keeps_risk_at_or_above_the_floor():
    d = dim(card(good(risk_check=risk(finding("h", "high")))), "sensitivity_risk")  # 0.7*40 + 0.3*10 = 31
    assert d.value == s2.OPEN_HIGH_FLOOR and d.rule_ids[-1] == "R3_open_high_floor"
    resolved = dim(card(good(risk_check=risk(finding("h", "high", status="resolved")))), "sensitivity_risk")
    assert resolved.value == 3.0 and "R3_open_high_floor" not in resolved.rule_ids


def test_a_risk_check_with_no_findings_is_low_risk_but_says_it_proves_nothing():
    c = card(good())
    assert dim(c, "sensitivity_risk").value == 3.0
    assert any("not proof that no risk exists" in x for x in c.limitations)


def test_o1_objective_status_weights_primary_double_and_o2_caps_a_missed_primary():
    mixed = [objective("met", True, "p"), objective("partly_met", False, "a"), objective("not_met", False, "b")]
    d = dim(card(good(objective_checks=mixed)), "objective_consistency")  # (2*1 + 0.5 + 0) / 4
    assert d.value == 62.5 and d.rule_ids == ["O1_objective_status"]
    missed = [objective("not_met", True, "p"), objective("met", False, "a"), objective("met", False, "b")]
    capped = dim(card(good(objective_checks=missed)), "objective_consistency")  # (0 + 1 + 1) / 4 = 50 -> 40
    assert capped.value == s2.PRIMARY_OBJECTIVE_MISSED_CAP and capped.rule_ids == ["O1_objective_status", "O2_primary_objective_cap"]


@pytest.mark.parametrize(
    ("missing", "name"),
    [
        ({"quick_read": None}, "message_clarity"),
        ({"quick_read": None}, "cultural_relevance"),
        ({"transcreation": None}, "brand_fidelity"),
        ({"risk_check": None}, "sensitivity_risk"),
        ({"objective_checks": []}, "objective_consistency"),
    ],
)
def test_a1_a_dimension_without_its_primary_input_is_not_assessed_never_defaulted(missing, name):
    d = dim(card(good(**missing)), name)
    assert d.value is None and d.utility is None and d.rule_ids == ["A1_primary_input_required"]
    assert d.missing_inputs and "not assessed" in d.explanation


def test_an_unrun_risk_check_is_not_low_risk():
    c = card(good(risk_check=None))
    assert dim(c, "sensitivity_risk").value is None and not c.complete
    assert any("Not assessed" in x and "Sensitivity risk" in x for x in c.limitations)


# --- aggregation ----------------------------------------------------------------------------------


def test_a2_overall_is_the_weighted_utility_with_risk_inverted():
    c = card(good())
    values = {d.dimension: d.value for d in c.dimensions}
    assert values == {
        "message_clarity": 83.0, "brand_fidelity": 100.0, "cultural_relevance": 72.0, "sensitivity_risk": 3.0,
        "objective_consistency": 100.0,
    }
    # 0.25*83 + 0.20*100 + 0.25*72 + 0.20*(100-3) + 0.10*100 = 88.15 (a half-point tie, so allow either rounding)
    assert c.overall == pytest.approx(88.15, abs=0.051) and c.coverage == 1.0 and c.complete
    assert c.rule_ids[-1] == "A2_overall_weighted_utility"
    assert dim(c, "sensitivity_risk").utility == 97.0


def test_a2_overall_renormalises_over_what_was_assessed():
    c = card(good(objective_checks=[], references=None))  # objective_consistency (0.10) not assessed
    assert c.coverage == pytest.approx(0.9) and not c.complete
    assert c.overall == pytest.approx((0.25 * 83 + 0.2 * 100 + 0.25 * 70 + 0.2 * 97) / 0.9, abs=0.06)


def test_a3_overall_is_null_below_half_coverage():
    only_objective = card(v.VersionObservations(objective_checks=[objective()]))
    assert only_objective.overall is None and only_objective.coverage == pytest.approx(0.1)
    assert only_objective.rule_ids[-1] == "A3_min_coverage"
    panel_only = card(v.VersionObservations(quick_read=quick_read()))  # clarity + relevance = exactly 0.5
    assert panel_only.overall is not None and panel_only.coverage == 0.5


def test_every_rule_id_a_card_can_carry_is_documented():
    cards = [
        card(good()), card(good(risk_check=risk(finding("h", "high")))), card(v.VersionObservations()),
        card(good(transcreation=transcreation(script_error_lines=1, glossary_violation_lines=1, prohibited_term_lines=1),
                  objective_checks=[objective("not_met")])),
    ]
    used = {r for c in cards for r in c.rule_ids} | {r for c in cards for d in c.dimensions for r in d.rule_ids}
    assert used <= set(s2.RULES)


def test_same_inputs_give_the_same_card_every_time():
    o, version_id = good(risk_check=risk(finding("a"), finding("b", "high"))), uuid4()
    first, second = s2.score_version(version_id, "A", o), s2.score_version(version_id, "A", o.model_copy(deep=True))
    assert first.model_dump() == second.model_dump()


def test_a_card_is_labelled_with_its_synthetic_basis_and_small_panel():
    c = card(good(quick_read=quick_read(respondents=8, understood=6, relevant=5, concerned=1)))
    text = " ".join(c.limitations)
    assert "synthetic panel of 8" in text and "not independent observations" in text and "panel is small" in text


def test_missing_and_weak_evidence_is_a_limitation_not_a_score_input():
    assert any("No Evidence Meter reading" in x for x in card(good(evidence_meter=None)).limitations)
    weak = card(good(evidence_meter=meter("weak")))
    assert any("reads weak" in x for x in weak.limitations)
    assert weak.overall == card(good()).overall  # evidence strength gates readiness; it does not change the score


# --- comparison -----------------------------------------------------------------------------------


def test_comparable_when_everything_matches():
    prov = v.Provenance(model_id="gemini-x", prompt_version="p1", criteria_version="c1", evidence_snapshot="e1")
    result = s2.compare("IN-TN", [version("A", good(provenance=prov)), version("B", good(provenance=prov))])
    assert result.comparability.comparable and result.comparability.notes == []


@pytest.mark.parametrize(
    ("field", "flag", "word"),
    [
        ("model_id", "same_model", "model"),
        ("prompt_version", "same_prompt_version", "prompt version"),
        ("criteria_version", "same_criteria", "evaluation criteria"),
        ("evidence_snapshot", "same_evidence", "evidence"),
    ],
)
def test_a_difference_in_model_prompt_criteria_or_evidence_is_disclosed(field, flag, word):
    a = v.Provenance(**{field: "one"})
    b = v.Provenance(**{field: "two"})
    result = s2.compare("IN-TN", [version("Alpha", good(provenance=a)), version("Beta", good(provenance=b))])
    c = result.comparability
    assert getattr(c, flag) is False and c.comparable is False
    note = next(n for n in c.notes if word in n)
    assert "differs between versions" in note and "Alpha: one" in note and "Beta: two" in note
    assert "not a like-for-like comparison" in " ".join(result.notes)


def test_a_value_recorded_for_one_version_and_not_the_other_is_a_difference():
    result = s2.compare("IN-TN", [version("A", good(provenance=v.Provenance(model_id="m"))), version("B", good())])
    assert not result.comparability.same_model and "B: not recorded" in result.comparability.notes[0]


def test_unrecorded_provenance_is_said_to_be_unrecorded():
    result = s2.compare("IN-TN", [version("A", good()), version("B", good())])
    assert result.comparability.comparable and any("was not recorded for any version" in n for n in result.comparability.notes)


def test_different_assessed_dimensions_are_disclosed():
    result = s2.compare("IN-TN", [version("A", good()), version("B", good(objective_checks=[]))])
    assert not result.comparability.same_dimensions_assessed and not result.comparability.comparable
    assert any("Different dimensions were assessed" in n for n in result.comparability.notes)


def test_ranking_orders_by_overall_and_puts_unscored_last():
    mid = good(quick_read=quick_read(understood=5, relevant=4))
    result = s2.compare("IN-TN", [version("mid", mid), version("best", good()), version("none", v.VersionObservations())])
    assert [(r.rank, r.label) for r in result.ranking] == [(1, "best"), (2, "mid"), (3, "none")]
    assert result.ranking[2].overall is None


def test_equal_overalls_keep_request_order():
    twins = [version("first", good()), version("second", good())]
    assert [r.label for r in s2.compare("IN-TN", twins).ranking] == ["first", "second"]
    assert [r.label for r in s2.compare("IN-TN", twins[::-1]).ranking] == ["second", "first"]


def test_equal_overalls_prefer_lower_sensitivity_risk():
    low = s2.score_version(uuid4(), "low", good())
    riskier = [d.model_copy(update={"value": 50.0}) if d.dimension == "sensitivity_risk" else d for d in low.dimensions]
    high = low.model_copy(update={"label": "high", "version_id": uuid4(), "dimensions": riskier})  # same overall, more risk
    assert [r.label for r in s2.rank([high, low])] == ["low", "high"]


def test_a_margin_under_five_points_is_not_meaningful():
    a = good()
    b = good(quick_read=quick_read(understood=7))  # clarity 76 against 83: about 1.8 points of overall
    close = s2.compare("IN-TN", [version("a", a), version("b", b)])
    assert close.meaningful_margin is False and any("no meaningful difference" in n for n in close.notes)
    far = s2.compare("IN-TN", [version("a", a), version("b", good(quick_read=quick_read(understood=3, relevant=3)))])
    assert far.meaningful_margin is True


def test_major_differences_name_the_leader_and_invert_risk():
    a, b = version("a", good()), version("b", good(risk_check=risk(finding("m", "medium"), finding("n", "medium"))))
    result = s2.compare("IN-TN", [a, b, version("c", good(transcreation=transcreation(glossary_violation_lines=3)))])
    by_dimension = {d.dimension: d for d in result.major_differences}
    assert set(by_dimension) == {"brand_fidelity", "sensitivity_risk"}
    assert by_dimension["brand_fidelity"].leader_version_id == a.version_id and by_dimension["brand_fidelity"].spread == 30.0
    assert by_dimension["sensitivity_risk"].leader_version_id == a.version_id  # lower risk leads
    assert sorted(x.value for x in by_dimension["sensitivity_risk"].values) == [3.0, 3.0, 24.0]


def test_comparison_carries_the_methodology_and_a_synthetic_note():
    result = s2.compare("IN-TN", [version("a", good()), version("b", good())])
    assert result.methodology.version == "mvp-2" and result.scoring_version == "mvp-2"
    assert any("do not predict market performance" in n for n in result.notes)


# --- input validation -----------------------------------------------------------------------------


def test_quick_read_counts_must_fit_the_panel():
    for bad in ({"understood": 11}, {"understood": 6, "confused": 5}, {"positive": 6, "negative": 5}):
        with pytest.raises(ValidationError):
            quick_read(**bad)
    assert quick_read().synthetic is True


def test_requests_need_two_to_four_unique_versions():
    one = version("a", good())
    with pytest.raises(ValidationError):
        v.ScoreCompareRequest(region_code="IN-TN", versions=[one])
    with pytest.raises(ValidationError):
        v.ScoreCompareRequest(region_code="IN-TN", versions=[version(str(i), good()) for i in range(5)])
    with pytest.raises(ValidationError):
        v.ScoreCompareRequest(region_code="IN-TN", versions=[one, one])
    with pytest.raises(ValidationError):
        v.ScoreCompareRequest(region_code="in-tn", versions=[one, version("b", good())])


def test_transcreation_and_finding_inputs_are_validated():
    with pytest.raises(ValidationError):
        transcreation(glossary_violation_lines=11)
    with pytest.raises(ValidationError):
        transcreation(glossary_violation_lines=1, prohibited_term_lines=2)
    with pytest.raises(ValidationError):
        risk(finding("same"), finding("same"))
