"""Launch observations gathered on the server: Compare and Score `mvp-2` and Readiness `ready-1` read the latest stored
Quick Read, Risk Check, transcreation, X-Ray and evidence records when a request carries no observations, and say what they
read and what was missing. Client-supplied observations keep working unchanged."""

from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import select

from app.db import models as m
from app.db.session import read_session
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
from tests.api.launch_support import good, observations_json, quick_read
from tests.api.omnicult_support import all_claims, seeded  # noqa: F401
from tests.api.proof_support import campaign_with_regions, tamil_nadu_claims

TN = "IN-TN"


async def setup(client: httpx.AsyncClient) -> dict[str, Any]:
    base = await campaign_with_regions(client)
    await tamil_nadu_claims(base["workspace_id"])
    cid = base["campaign"]["id"]
    return {**base, "cid": cid, "pid": base["project"]["id"], "url": f"{API}/campaigns/{cid}", "root": await root_version(client, cid)}


async def light(client: httpx.AsyncClient) -> dict[str, Any]:
    """Another campaign with one version and no claims."""
    base = await campaign_with_regions(client)
    cid = base["campaign"]["id"]
    return {**base, "cid": cid, "pid": base["project"]["id"], "url": f"{API}/campaigns/{cid}", "root": await root_version(client, cid)}


def four_responses() -> list[dict[str, Any]]:
    return [
        quick_read_response(survival="understood", sentiment="positive", relevance=4),
        quick_read_response(survival="partial", sentiment="mixed", relevance=2, concern=True),
        quick_read_response(survival="misunderstood", sentiment="negative", relevance=5, concern=True),
        quick_read_response(survival="understood", sentiment="confused", relevance=3),
    ]


async def verdict_inputs() -> dict[str, Any]:
    async with read_session() as s:
        return (await s.execute(select(m.ReadinessVerdict).order_by(m.ReadinessVerdict.computed_at.desc()))).scalars().first().inputs  # type: ignore[union-attr]


def by_name(items: list[dict[str, Any]], key: str = "observation") -> dict[str, dict[str, Any]]:
    return {i[key]: i for i in items}


async def test_readiness_without_observations_reads_stored_records_and_reports_what_it_read(seeded: Any, client: httpx.AsyncClient) -> None:
    s = await setup(client)
    quick = await add_quick_read(s["cid"], s["pid"], s["root"]["id"], four_responses())
    risk = await add_risk_check(s["cid"], s["pid"], s["root"]["id"], [
        {"severity": "high", "blocks_go": True, "status": "accepted"}, {"severity": "low", "status": "fixed"}, {"severity": "medium", "status": "dismissed"}])
    response = await client.post(f"{s['url']}/readiness", json={"region_code": TN, "version_id": s["root"]["id"]})
    assert response.status_code == 201, response.text
    verdict = response.json()
    sources = verdict["observation_sources"]
    assert (sources["origin"], sources["version_id"]) == ("gathered", s["root"]["id"])
    gathered = by_name(sources["gathered"])
    assert set(gathered) == {"quick_read", "risk_check", "evidence_meter", "open_conflicts"}
    assert gathered["quick_read"]["record_ids"] == [str(quick)] and gathered["quick_read"]["synthetic"] is True
    assert gathered["risk_check"]["record_ids"] == [str(risk)] and gathered["risk_check"]["synthetic"] is False
    missing = by_name(sources["missing"])
    assert set(missing) == {"transcreation", "references", "objective_checks"}
    assert "never gathered" in missing["objective_checks"]["reason"] and "was not produced by a transcreation" in missing["transcreation"]["reason"]
    stored = await verdict_inputs()
    assert stored["quick_read"] | {"evidence_ids": []} == {
        "respondents": 4, "understood": 2, "confused": 1, "positive": 1, "negative": 1, "relevant": 2, "concerned": 2,
        "synthetic": True, "evidence_ids": []}
    assert len(stored["quick_read"]["evidence_ids"]) == 1  # the claim the panel cited
    findings = by_name(stored["risk_check"]["findings"], "severity")
    assert (findings["high"]["status"], findings["high"]["blocks_go"]) == ("open", True)  # an accepted finding still counts
    assert (findings["low"]["status"], findings["medium"]["status"]) == ("resolved", "dismissed")
    assert stored["risk_check"]["run_id"] == str(risk) and stored["evidence_meter"]["strength"] in ("weak", "partial", "solid")
    assert stored["provenance"]["run_ids"] == [str(quick), str(risk)]
    assert stored["provenance"]["model_id"] == "gemini-3.5-flash-lite" and stored["provenance"]["prompt_version"] == "quick-read.v1"
    assert stored["provenance"]["criteria_version"].startswith("panel-") and stored["provenance"]["evidence_snapshot"].startswith("claims-")
    assert verdict["verdict"] in ("fix", "rethink")  # an open blocking finding rules out Go
    again = await client.post(f"{s['url']}/readiness", json={"region_code": TN, "version_id": s["root"]["id"]})
    assert again.status_code == 200 and again.json()["id"] == verdict["id"]  # identical gathered inputs: the stored verdict
    history = (await client.get(f"{s['url']}/readiness/history")).json()["items"]
    assert history[0]["observation_sources"]["origin"] == "gathered"


async def test_compare_gathers_for_the_versions_that_send_none_and_uses_supplied_observations_as_sent(seeded: Any, client: httpx.AsyncClient) -> None:
    s = await setup(client)
    await add_quick_read(s["cid"], s["pid"], s["root"]["id"], [quick_read_response()] * 4)
    await add_risk_check(s["cid"], s["pid"], s["root"]["id"], [])
    other = (await edit_version(client, s["cid"], s["root"]["id"]))["version"]["id"]
    body = {"region_code": TN, "versions": [
        {"version_id": s["root"]["id"], "label": "Gathered"},
        {"version_id": other, "label": "Supplied", "observations": observations_json(quick_read=quick_read(respondents=10, understood=5).model_dump(mode="json"))},
    ]}
    response = await client.post(f"{s['url']}/scores/compare", json=body)
    assert response.status_code == 200, response.text
    comparison = response.json()
    first, second = comparison["observation_sources"]
    assert (first["origin"], second["origin"]) == ("gathered", "supplied")
    assert second["gathered"] == [] and second["missing"] == [] and second["notes"]  # everything was supplied: nothing read
    clarity = by_name(comparison["cards"][0]["dimensions"], "dimension")["message_clarity"]
    assert clarity["value"] == 100.0 and clarity["inputs_used"][0]["signal"] == "quick_read.understood_share"
    supplied_clarity = by_name(comparison["cards"][1]["dimensions"], "dimension")["message_clarity"]
    assert supplied_clarity["inputs_used"][0]["value"] == 50.0  # 5 of 10, as sent
    sensitivity = by_name(comparison["cards"][0]["dimensions"], "dimension")["sensitivity_risk"]
    assert sensitivity["value"] is not None  # a completed Risk Check with no findings is an observation, not a gap
    assert any("not proof that no risk exists" in x for x in comparison["cards"][0]["limitations"])


async def test_supplied_observations_report_what_the_request_left_out(seeded: Any, client: httpx.AsyncClient) -> None:
    s = await setup(client)
    other = (await edit_version(client, s["cid"], s["root"]["id"]))["version"]["id"]
    only_panel = {"quick_read": quick_read().model_dump(mode="json")}
    body = {"region_code": TN, "versions": [
        {"version_id": s["root"]["id"], "label": "A", "observations": only_panel},
        {"version_id": other, "label": "B", "observations": observations_json()},
    ]}
    sources = (await client.post(f"{s['url']}/scores/compare", json=body)).json()["observation_sources"]
    assert {x["observation"] for x in sources[0]["missing"]} == {"risk_check", "transcreation", "references", "objective_checks", "evidence_meter"}
    assert all(x["reason"] == "Not supplied in the request." for x in sources[0]["missing"]) and sources[1]["missing"] == []
    verdict = await client.post(f"{s['url']}/readiness", json={"region_code": TN, "version_id": s["root"]["id"], "observations": good().model_dump(mode="json")})
    assert verdict.status_code == 201 and verdict.json()["observation_sources"]["origin"] == "supplied"


async def test_only_completed_runs_for_this_version_and_region_are_read(seeded: Any, client: httpx.AsyncClient) -> None:
    s = await setup(client)
    other = (await edit_version(client, s["cid"], s["root"]["id"]))["version"]["id"]
    older = await add_quick_read(s["cid"], s["pid"], s["root"]["id"], [quick_read_response()] * 3)
    await add_quick_read(s["cid"], s["pid"], s["root"]["id"], [quick_read_response()] * 5, status="running")
    await add_quick_read(s["cid"], s["pid"], s["root"]["id"], [quick_read_response()] * 5, status="failed")
    await add_quick_read(s["cid"], s["pid"], s["root"]["id"], [quick_read_response()] * 7, region="IN-KL")  # another region
    await add_quick_read(s["cid"], s["pid"], other, [quick_read_response()] * 9)  # another version
    await add_quick_read(s["cid"], s["pid"], None, [quick_read_response()] * 11)  # tied to no version
    sources = (await client.post(f"{s['url']}/readiness", json={"region_code": TN, "version_id": s["root"]["id"]})).json()["observation_sources"]
    assert by_name(sources["gathered"])["quick_read"]["record_ids"] == [str(older)]
    assert (await verdict_inputs())["quick_read"]["respondents"] == 3
    newer = await add_quick_read(s["cid"], s["pid"], s["root"]["id"], [quick_read_response()] * 4, status="partial")  # a partial run is usable
    again = (await client.post(f"{s['url']}/readiness", json={"region_code": TN, "version_id": s["root"]["id"]})).json()
    assert by_name(again["observation_sources"]["gathered"])["quick_read"]["record_ids"] == [str(newer)]
    assert (await client.get(f"{s['url']}/readiness/history")).json()["total"] == 2  # changed inputs add history


async def test_a_version_without_records_is_scored_as_missing_never_as_zero(seeded: Any, client: httpx.AsyncClient) -> None:
    s = await setup(client)
    other = (await edit_version(client, s["cid"], s["root"]["id"]))["version"]["id"]
    body = {"region_code": TN, "versions": [{"version_id": s["root"]["id"], "label": "A"}, {"version_id": other, "label": "B"}]}
    comparison = (await client.post(f"{s['url']}/scores/compare", json=body)).json()
    first = comparison["observation_sources"][0]
    assert {x["observation"] for x in first["missing"]} >= {"quick_read", "risk_check", "transcreation", "references", "objective_checks"}
    dimensions = by_name(comparison["cards"][0]["dimensions"], "dimension")
    assert dimensions["message_clarity"]["value"] is None and dimensions["sensitivity_risk"]["value"] is None
    assert dimensions["message_clarity"]["missing_inputs"] == ["quick_read"]
    assert comparison["cards"][0]["overall"] is None and comparison["comparability"]["comparable"] in (True, False)


async def test_transcreation_checks_are_counted_in_code_from_the_operation_that_made_the_version(seeded: Any, client: httpx.AsyncClient) -> None:
    s = await setup(client)
    lines = [
        transcreate_line("headline"), transcreate_line("cta", protected_ok=False, passed=False),
        transcreate_line("tagline", prohibited=True), transcreate_line("body", script_ok=False, passed=False),
    ]
    _, node = await add_transcreation(s["cid"], s["pid"], s["root"]["id"], lines)
    _, other_region = await add_transcreation(s["cid"], s["pid"], s["root"]["id"], [transcreate_line()], region="IN-KL")
    response = await client.post(f"{s['url']}/readiness", json={"region_code": TN, "version_id": str(node)})
    assert response.status_code == 201, response.text
    stored = (await verdict_inputs())["transcreation"]
    assert stored == {"lines_checked": 4, "glossary_violation_lines": 2, "prohibited_term_lines": 1, "meaning_preserved_lines": None,
                      "script_error_lines": 1}
    sources = response.json()["observation_sources"]
    detail = by_name(sources["gathered"])["transcreation"]
    assert "2 of them failed a check and were not applied" in detail["detail"] and detail["record_ids"]
    assert any("back-translation meaning is not gathered" in x for x in sources["notes"])
    wrong_region = (await client.post(f"{s['url']}/readiness", json={"region_code": TN, "version_id": str(other_region)})).json()
    assert "transcreation" in {x["observation"] for x in wrong_region["observation_sources"]["missing"]}  # made for another region


async def test_references_count_xray_observations_and_how_many_carry_a_claim_link(seeded: Any, client: httpx.AsyncClient) -> None:
    s = await setup(client)
    claim = str(uuid4())
    await add_creative(s["cid"], s["pid"], cultural=[
        {"id": "o1", "text": "A rangoli.", "category": "symbol", "evidence": ["f1"], "claim_ids": [claim]},
        {"id": "o2", "text": "A diya.", "category": "symbol", "evidence": ["f1"], "claim_ids": []}])
    await add_creative(s["cid"], s["pid"], region="IN-KL", label="Kerala film")  # read for another market: not counted
    first = (await client.post(f"{s['url']}/readiness", json={"region_code": TN, "version_id": s["root"]["id"]})).json()
    detail = by_name(first["observation_sources"]["gathered"])["references"]
    assert "2 cultural observation(s)" in detail["detail"] and len(detail["record_ids"]) == 1
    assert (await verdict_inputs())["references"] == {"references_checked": 2, "references_supported": 1}
    unlinked = await light(client)
    await add_creative(unlinked["cid"], unlinked["pid"])
    second = (await client.post(f"{unlinked['url']}/readiness", json={"region_code": TN, "version_id": unlinked["root"]["id"]})).json()
    assert (await verdict_inputs())["references"] == {"references_checked": 1, "references_supported": 0}
    assert any("None of the X-Ray observations is linked to an evidence claim" in x for x in second["observation_sources"]["notes"])


async def test_evidence_meter_and_unresolved_conflicts_are_read_and_marked_relied_on_through_the_versions_claims(
    seeded: Any, client: httpx.AsyncClient
) -> None:
    s = await setup(client)
    shared = [c for c in await all_claims() if c.attribute == "language_share"]
    assert len(shared) == 2
    _, node = await add_transcreation(s["cid"], s["pid"], s["root"]["id"], [transcreate_line()], claim_ids=[shared[0].id])
    relied = (await client.post(f"{s['url']}/readiness", json={"region_code": TN, "version_id": str(node)})).json()
    stored = (await verdict_inputs())["open_conflicts"]
    assert len(stored) == 1 and stored[0]["relied_on"] is True and stored[0]["status"] == "open"
    assert set(stored[0]["claim_ids"]) == {str(c.id) for c in shared}
    assert by_name(relied["observation_sources"]["gathered"])["open_conflicts"]["record_ids"] == [stored[0]["conflict_id"]]
    await client.post(f"{s['url']}/readiness", json={"region_code": TN, "version_id": s["root"]["id"]})  # the root cites no claim
    assert (await verdict_inputs())["open_conflicts"][0]["relied_on"] is False
    assert (await verdict_inputs())["evidence_meter"]["claims"] == 5  # the five Tamil Nadu claims


async def test_an_unknown_version_is_refused_cleanly_with_or_without_observations(seeded: Any, client: httpx.AsyncClient) -> None:
    s = await setup(client)
    ghost = str(uuid4())
    for body in ({"region_code": TN, "version_id": ghost}, {"region_code": TN, "version_id": ghost, "observations": observations_json()}):
        response = await client.post(f"{s['url']}/readiness", json=body)
        assert response.status_code == 404, response.text
    approval = await client.post(f"{s['url']}/approvals", json={
        "region_code": TN, "version_id": ghost, "decision": "approve", "reason": "Looks fine to me."})
    assert approval.status_code == 404
    gathered = await client.post(f"{s['url']}/scores/compare", json={"region_code": TN, "versions": [
        {"version_id": ghost, "label": "A"}, {"version_id": s["root"]["id"], "label": "B"}]})
    assert gathered.status_code == 404
    other = await light(client)  # a version of another campaign is not a version of this one
    cross = await client.post(f"{s['url']}/readiness", json={"region_code": TN, "version_id": other["root"]["id"]})
    assert cross.status_code == 404
    async with read_session() as db:
        assert (await db.execute(select(m.ReadinessVerdict))).first() is None and (await db.execute(select(m.Approval))).first() is None
