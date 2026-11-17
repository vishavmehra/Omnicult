"""Risk Check severity rules (risk-rules-v1) and the ASCI ad-code index dataset."""

import json
import re
from urllib.parse import urlparse

from app.analytics.risk_rules import (
    CATEGORY_RULES,
    PATTERNS,
    RULES_VERSION,
    ClaimSupport,
    claim_features,
    decide,
    scan_patterns,
    topics_fit,
)
from app.reference.ad_codes import DATASET, entries_by_id, load_index

CLAIM_OK = ClaimSupport("observed", "moderate")


def rules(decision) -> list[str]:
    return [r.rule for r in decision.rules]


def test_a_brand_rule_hit_is_high_and_blocks_go_without_any_model():
    d = decide("brand_rule", ad_code_topics=[], claims=[], quote="cheap", deterministic=True)
    assert (d.severity, d.blocks_go, d.confidence) == ("high", True, "moderate")
    assert rules(d) == ["R1_base", "R7_blocks_go"]


def test_model_interpretation_alone_is_capped_at_medium_and_never_blocks():
    d = decide("unsubstantiated_claim", ad_code_topics=[], claims=[], quote="100% guaranteed results")
    assert d.severity == "medium" and not d.blocks_go and d.confidence == "insufficient"
    assert "R4_hard_claim" in rules(d) and "R5_cap" in rules(d)


def test_a_fitting_ad_code_clause_raises_severity_and_can_block():
    d = decide("unsubstantiated_claim", ad_code_topics=[["claims", "substantiation"]], claims=[], quote="a pleasant line")
    assert d.severity == "high" and d.blocks_go and "R2_ad_code" in rules(d) and d.confidence == "limited"


def test_an_ad_code_clause_that_does_not_fit_the_category_changes_nothing():
    d = decide("comparative_claim", ad_code_topics=[["children"]], claims=[], quote=None)
    assert d.severity == "medium" and "R2_ad_code" not in rules(d)


def test_only_observed_or_calculated_claims_at_moderate_or_better_escalate():
    base = dict(ad_code_topics=[], quote=None)
    assert decide("offensive_content", claims=[ClaimSupport("observed", "moderate")], **base).severity == "high"
    assert decide("offensive_content", claims=[ClaimSupport("calculated", "high")], **base).severity == "high"
    for weak in (ClaimSupport("interpretation", "high"), ClaimSupport("synthetic", "moderate"), ClaimSupport("unverified", "high"),
                 ClaimSupport("observed", "low")):
        d = decide("offensive_content", claims=[weak], **base)
        assert d.severity == "medium" and "R3_claim" not in rules(d), weak


def test_hard_claim_wording_raises_claim_categories_only():
    quote = "Cures diabetes, 100% guaranteed"
    assert decide("health_nutrition_claim", ad_code_topics=[["health_food"]], claims=[], quote=quote).severity == "high"
    assert "R4_hard_claim" not in rules(decide("offensive_content", ad_code_topics=[], claims=[], quote=quote))


def test_high_severity_blocks_only_in_categories_that_can_block():
    d = decide("disclaimer_issue", ad_code_topics=[["disclaimers"]], claims=[CLAIM_OK], quote=None)
    assert d.severity == "high" and not d.blocks_go
    d = decide("regional_sensitivity", ad_code_topics=[["offence"]], claims=[CLAIM_OK], quote=None)
    assert d.severity == "high" and d.blocks_go
    d = decide("regional_sensitivity", ad_code_topics=[], claims=[CLAIM_OK], quote=None)
    assert d.severity == "medium" and not d.blocks_go


def test_severity_never_exceeds_high_and_every_step_is_explained():
    d = decide("unsubstantiated_claim", ad_code_topics=[["claims"]], claims=[CLAIM_OK], quote="100% safe")
    assert d.severity == "high" and rules(d)[:4] == ["R1_base", "R2_ad_code", "R3_claim", "R4_hard_claim"]
    assert all(r.reason and r.effect for r in d.rules) and RULES_VERSION == "risk-rules-v1"


def test_the_decision_is_deterministic():
    args = dict(ad_code_topics=[["claims"]], claims=[CLAIM_OK], quote="No.1 in India")
    assert decide("comparative_claim", **args) == decide("comparative_claim", **args)


def test_claim_features_and_patterns():
    assert {"100%", "better than"} <= set(claim_features("Better than any rival, 100% natural"))
    assert claim_features("A calm autumn morning") == [] and claim_features(None) == []
    hits = scan_patterns("Clinically proven. No.1 in India. Guaranteed glow!")
    assert [h.category for h in hits] == ["health_nutrition_claim", "comparative_claim", "unsubstantiated_claim"]
    assert scan_patterns("Festive offers for the whole family") == []


def test_every_category_has_a_rule_and_topics_fit_is_exact():
    assert {"brand_rule", "other"} <= set(CATEGORY_RULES)
    assert topics_fit("comparative_claim", ["comparisons"]) and not topics_fit("comparative_claim", ["children"])
    assert topics_fit("other", ["anything"])


# --- the ASCI index dataset ---------------------------------------------------------------------------------------------


def test_the_index_loads_and_every_entry_is_cited_to_asci():
    index = load_index()
    assert index.publisher.startswith("Advertising Standards Council of India") and len(index.entries) >= 40
    ids = [e.id for e in index.entries]
    assert len(ids) == len(set(ids))
    for e in index.entries:
        assert urlparse(e.url).hostname.endswith("ascionline.in") and e.url.endswith(f"#page={e.pdf_page}"), e.id
        assert e.excerpt.strip() and not re.search(r"[\x00-\x1f]", e.excerpt) and "…" not in e.excerpt and "[...]" not in e.excerpt, e.id
        assert e.topics and e.document and e.clause and e.title
    assert re.fullmatch(r"[0-9a-f]{64}", index.source.sha256) and index.source.url.startswith("https://www.ascionline.in/")
    assert index.limitations and "not legal advice" in " ".join(index.limitations)


def test_the_index_covers_the_required_topics():
    topics = {t for e in load_index().entries for t in e.topics}
    assert {"claims", "comparisons", "health_food", "children", "safety", "offence"} <= topics
    chapters = {e.chapter.split(" - ")[0] for e in load_index().entries if e.document_kind == "code"}
    assert chapters == {"Chapter I", "Chapter II", "Chapter III", "Chapter IV"}


def test_every_ad_code_id_the_rules_name_exists_and_fits_its_category():
    by_id = entries_by_id()
    for _, category, _, ids in PATTERNS:
        for entry_id in ids:
            assert entry_id in by_id, entry_id
            assert topics_fit(category, by_id[entry_id].topics), (category, entry_id)


def test_every_blockable_category_has_ad_code_entries_to_cite():
    index = load_index()
    for category, (_, _, topics) in CATEGORY_RULES.items():
        if topics:
            assert any(set(e.topics) & topics for e in index.entries), category


def test_the_dataset_file_is_utf8_json_with_the_documented_shape():
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    assert data["version"] == "asci-index-v1" and data["retrieved_at"] == "2026-11-17"
    assert set(data["source"]) >= {"url", "sha256", "edition", "bytes", "pages", "note"}


def test_known_exact_excerpts():
    by_id = entries_by_id()
    assert by_id["asci-1-1"].excerpt.startswith("Advertisements must be truthful. All descriptions, claims and comparisons")
    assert by_id["asci-3-2"].excerpt.startswith("Advertisements addressed to children shall not contain anything")
    assert by_id["asci-4-1-e"].excerpt == ("The advertisement does not unfairly denigrate, attack or discredit other products, "
                                           "advertisers or advertisements directly or by implication.")
