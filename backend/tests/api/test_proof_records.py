"""Proof Report sections fed by the other streams' records: Creative Studio, X-Ray, Audience Lab, Launch Room and Pulse.
Every provider reads stored rows, labels what it shows (synthetic stays synthetic, sample stays sample) and reports missing
data as missing."""

from typing import Any
from uuid import UUID, uuid4

import httpx

from tests.api.glue_support import (
    API,
    add_creative,
    add_quick_read,
    add_risk_check,
    add_transcreation,
    edit_version,
    quick_read_response,
    root_version,
    transcreate_line,
)
from tests.api.launch_support import observations_json
from tests.api.omnicult_support import seeded  # noqa: F401
from tests.api.proof_support import campaign_with_regions, tamil_nadu_claims
from tests.api.test_proof_report import make_report, section

TN = "IN-TN"


async def full_campaign(client: httpx.AsyncClient) -> dict[str, Any]:
    """A campaign with a version tree, a transcreation, an analysed creative, Audience Lab runs, a verdict, an approval and
    the sample performance dataset."""
    setup = await campaign_with_regions(client)
    await tamil_nadu_claims(setup["workspace_id"])
    cid, pid = setup["campaign"]["id"], setup["project"]["id"]
    root = await root_version(client, cid)
    edited = await edit_version(client, cid, root["id"])
    claim = uuid4()
    op_id, trans_id = await add_transcreation(
        cid, pid, root["id"], [transcreate_line(), transcreate_line("cta", passed=False, protected_ok=False, script_ok=False)], claim_ids=[claim])
    creative_id, scene_id = await add_creative(cid, pid)
    quick = await add_quick_read(cid, pid, root["id"], [quick_read_response(), quick_read_response(sentiment="mixed", relevance=2)], disagree=True)
    risk = await add_risk_check(cid, pid, root["id"], [
        {"severity": "high", "source": "deterministic_check", "blocks_go": True}, {"severity": "low", "status": "fixed"}])
    verdict = await client.post(f"{API}/campaigns/{cid}/readiness", json={
        "region_code": TN, "version_id": root["id"], "observations": observations_json()})
    assert verdict.status_code == 201, verdict.text
    approval = await client.post(f"{API}/campaigns/{cid}/approvals", json={
        "region_code": TN, "version_id": root["id"], "decision": "approve", "reason": "Reviewed with the regional lead."})
    assert approval.status_code == 201, approval.text
    loaded = await client.post(f"{API}/campaigns/{cid}/pulse/sample-dataset")
    assert loaded.status_code == 200, loaded.text
    return {**setup, "cid": cid, "root": root, "edited": edited, "op": op_id, "trans": trans_id, "creative": creative_id, "scene": scene_id,
            "quick": quick, "risk": risk, "verdict": verdict.json(), "claim": claim}


async def test_every_record_section_is_available_with_typed_content_and_honest_labels(seeded: Any, client: httpx.AsyncClient) -> None:
    c = await full_campaign(client)
    report = await make_report(client, c["cid"])
    assert report["missing_sections"] == [] and report["status"] == "complete"
    for found in report["sections"]:
        assert found["status"] == "available" and found["kind_labels"], found["id"]
    kinds = {s["id"]: {k["kind"] for k in s["kind_labels"]} for s in report["sections"]}
    assert kinds["creative_versions"] == {"observed", "interpretation"}
    assert kinds["xray_findings"] == {"observed", "interpretation"}
    assert kinds["transcreation"] == {"interpretation", "calculated"}
    assert kinds["risk_findings"] == {"calculated", "interpretation"}
    assert kinds["audience_results"] == {"synthetic"}
    assert kinds["readiness"] == {"calculated"} and kinds["approvals"] == {"observed"}
    assert kinds["live_performance"] == {"synthetic"}  # the Live Pulse dataset, not a connected account


async def test_creative_versions_lists_the_tree_oldest_first_with_who_made_each(seeded: Any, client: httpx.AsyncClient) -> None:
    c = await full_campaign(client)
    versions = section(await make_report(client, c["cid"]), "creative_versions")["content"]
    assert [v["label"] for v in versions["versions"]][0] == "Original" and len(versions["versions"]) == 3
    by_id = {v["version_id"]: v for v in versions["versions"]}
    assert by_id[c["root"]["id"]]["operation"] is None and by_id[c["root"]["id"]]["kind"] == "observed"
    ai = by_id[str(c["trans"])]
    assert (ai["operation"], ai["actor"], ai["kind"], ai["parent_version_id"]) == ("transcreate", "ai", "interpretation", c["root"]["id"])
    assert ai["claim_ids"] == [str(c["claim"])]
    manual = by_id[c["edited"]["version"]["id"]]
    assert (manual["operation"], manual["actor"], manual["summary"]) == ("replace_text", "user", "A tighter headline.")
    assert "compared with the original" in versions["comparison_summary"] and versions["truncated"] is False


async def test_xray_findings_keep_observed_text_apart_from_model_readings(seeded: Any, client: httpx.AsyncClient) -> None:
    c = await full_campaign(client)
    xray = section(await make_report(client, c["cid"]), "xray_findings")["content"]
    by_field = {f["field"]: f for f in xray["findings"]}
    assert set(by_field) == {"on_screen_text", "ad_claim", "cultural_observation", "cultural_interpretation"}
    assert by_field["on_screen_text"]["kind"] == by_field["ad_claim"]["kind"] == "observed"
    assert by_field["cultural_observation"]["kind"] == by_field["cultural_interpretation"]["kind"] == "interpretation"
    assert by_field["on_screen_text"]["observation"] == 'On-screen text: "Diwali sale"'
    assert by_field["on_screen_text"]["anchor"] == {"scene_id": str(c["scene"]), "start_ms": 0, "end_ms": 4000, "bbox": None}
    assert all(f["confidence"] is None and f["creative_label"] == "Diwali film" for f in xray["findings"])  # no confidence is invented
    assert (xray["creatives"], xray["scenes"], xray["truncated"]) == (1, 1, False)


async def test_transcreation_lines_show_failed_checks_and_the_back_translation_as_model_output(seeded: Any, client: httpx.AsyncClient) -> None:
    c = await full_campaign(client)
    items = section(await make_report(client, c["cid"]), "transcreation")["content"]["items"]
    assert [(i["region_code"], i["language"], i["kind"]) for i in items] == [(TN, "ta", "interpretation")] * 2
    ok, failed = items
    assert ok["glossary_issues"] == [] and ok["back_translation"] == "Happy Deepavali from Acme" and ok["claim_ids"] == []
    assert failed["glossary_issues"][0].startswith("Not applied") and "another script" in failed["glossary_issues"][1]
    assert ok["source_version_id"] == c["root"]["id"] and ok["result_version_id"] == str(c["trans"])


async def test_risk_findings_take_the_newest_run_and_computed_severity_is_calculated(seeded: Any, client: httpx.AsyncClient) -> None:
    c = await full_campaign(client)
    older = await add_risk_check(c["cid"], c["project"]["id"], c["root"]["id"], [{"severity": "low"}])  # newer than c["risk"]
    risk = section(await make_report(client, c["cid"]), "risk_findings")["content"]
    assert risk["run_ids"] == [str(older)]  # the newest usable run of the region only
    assert [(f["severity"], f["kind"]) for f in risk["findings"]] == [("low", "interpretation")]
    assert "not legal advice" in risk["disclaimer"].lower()
    full = await make_report(client, c["cid"], region_codes=["IN-KL"])  # no Risk Check exists for Kerala
    assert section(full, "risk_findings")["status"] == "missing"


async def test_risk_finding_detail_carries_anchor_ad_code_status_and_blocking(seeded: Any, client: httpx.AsyncClient) -> None:
    setup = await campaign_with_regions(client)
    cid, pid = setup["campaign"]["id"], setup["project"]["id"]
    root = await root_version(client, cid)
    await add_risk_check(cid, pid, root["id"], [
        {"severity": "high", "source": "deterministic_check", "blocks_go": True}, {"severity": "low", "status": "fixed"}])
    findings = section(await make_report(client, cid), "risk_findings")["content"]["findings"]
    high = findings[0]
    assert (high["severity"], high["kind"], high["blocks_go"], high["status"]) == ("high", "calculated", True, "open")
    assert high["ad_code_ref"] == "ASCI Code Chapter I.4" and high["region_code"] == TN and high["suggested_fix"]
    assert findings[1]["status"] == "fixed" and findings[1]["kind"] == "interpretation"


async def test_audience_results_are_synthetic_and_never_count_as_independent_observations(seeded: Any, client: httpx.AsyncClient) -> None:
    c = await full_campaign(client)
    results = section(await make_report(client, c["cid"]), "audience_results")["content"]["results"]
    (quick,) = results
    assert (quick["method"], quick["kind"], quick["respondent_count"], quick["region_code"]) == ("quick_read", "synthetic", 2, TN)
    assert quick["run_id"] == str(c["quick"]) and quick["model_ids"] == ["gemini-3.5-flash-lite"] and quick["mode"] == "live"
    assert "restated the intended message" in quick["summary"] and "split on cultural relevance" in quick["disagreement"]
    assert any("not independent human observations" in x for x in quick["limitations"])
    limits = " ".join(section(await make_report(client, c["cid"]), "limitations")["content"]["items"])
    assert "Audience results share one model's biases" in limits and "labelled sample dataset" not in limits and "not an approval" in limits


async def test_readiness_is_the_newest_verdict_with_the_others_listed(seeded: Any, client: httpx.AsyncClient) -> None:
    c = await full_campaign(client)
    second = await client.post(f"{API}/campaigns/{c['cid']}/readiness", json={
        "region_code": "IN-KL", "version_id": c["root"]["id"], "observations": observations_json()})
    assert second.status_code == 201
    content = section(await make_report(client, c["cid"]), "readiness")["content"]
    assert (content["verdict_id"], content["region_code"], content["kind"]) == (second.json()["id"], "IN-KL", "calculated")
    assert [o["verdict_id"] for o in content["other_verdicts"]] == [c["verdict"]["id"]]
    assert content["rule_version"] == "ready-1" and content["next_action"] and "not an approval" in content["note"]
    only_tn = section(await make_report(client, c["cid"], region_codes=[TN]), "readiness")["content"]
    assert only_tn["verdict_id"] == c["verdict"]["id"]


async def test_approvals_are_recorded_decisions_with_the_recommendation_in_force(seeded: Any, client: httpx.AsyncClient) -> None:
    c = await full_campaign(client)
    (approval,) = section(await make_report(client, c["cid"]), "approvals")["content"]["approvals"]
    assert (approval["decision"], approval["region_code"], approval["kind"], approval["note"]) == (
        "approved", TN, "observed", "Reviewed with the regional lead.")
    assert approval["version_id"] == c["root"]["id"] and approval["approver_user_id"] and approval["role"] is None
    assert approval["verdict_at_decision"] == "go" and approval["overrides_recommendation"] is False


async def test_live_performance_is_labelled_sample_and_drops_ratios_it_cannot_compute(seeded: Any, client: httpx.AsyncClient) -> None:
    c = await full_campaign(client)
    performance = section(await make_report(client, c["cid"]), "live_performance")["content"]
    assert performance["sample_data"] is True and performance["dataset_version"] and performance["note"] == "Figures from the Live Pulse dataset."
    assert performance["items"] and {i["kind"] for i in performance["items"]} == {"synthetic"}
    assert all(i["source"].startswith("Live Pulse dataset") and i["period"] and i["value"] is not None for i in performance["items"])
    assert {i["region_code"] for i in performance["items"]} == {TN, "IN-KL"}  # the campaign's target regions only
    assert len({i["version_label"] for i in performance["items"]}) == 3  # versions are reported apart, never blended
    only_kl = section(await make_report(client, c["cid"], region_codes=["IN-KL"]), "live_performance")["content"]
    assert {i["region_code"] for i in only_kl["items"]} <= {"IN-KL"}


async def test_a_campaign_with_no_records_reports_each_section_as_missing_with_its_reason(seeded: Any, client: httpx.AsyncClient) -> None:
    setup = await campaign_with_regions(client)
    await tamil_nadu_claims(setup["workspace_id"])
    report = await make_report(client, setup["campaign"]["id"])
    reasons = {s["id"]: s["missing_reason"] for s in report["sections"] if s["status"] == "missing"}
    assert set(reasons) == {"creative_versions", "xray_findings", "risk_findings", "transcreation", "audience_results", "readiness",
                            "approvals", "live_performance"}
    assert "No creative version" in reasons["creative_versions"] and "No performance data" in reasons["live_performance"]
    assert "not an approval" in reasons["approvals"] and "No readiness verdict" in reasons["readiness"]
    limits = " ".join(section(report, "limitations")["content"]["items"])
    assert "Audience results are synthetic" not in limits  # nothing synthetic is shown, so nothing is claimed about it


async def test_only_the_current_xray_analysis_and_the_target_regions_are_reported(seeded: Any, client: httpx.AsyncClient) -> None:
    setup = await campaign_with_regions(client)
    cid, pid = setup["campaign"]["id"], setup["project"]["id"]
    await add_creative(cid, pid, region="IN-KL", label="Kerala film")
    kerala = section(await make_report(client, cid, region_codes=[TN]), "xray_findings")
    assert kerala["status"] == "missing" and "target regions" in kerala["missing_reason"]
    anywhere = await make_report(client, cid, region_codes=["IN-KL"])
    assert section(anywhere, "xray_findings")["content"]["creatives"] == 1


async def test_records_of_another_campaign_never_appear(seeded: Any, client: httpx.AsyncClient) -> None:
    c = await full_campaign(client)
    other = await campaign_with_regions(client)
    report = await make_report(client, other["campaign"]["id"])
    assert section(report, "creative_versions")["status"] == "missing" and section(report, "audience_results")["status"] == "missing"
    assert str(c["root"]["id"]) not in str(report["sections"])
    assert UUID(c["cid"]) != UUID(other["campaign"]["id"])
