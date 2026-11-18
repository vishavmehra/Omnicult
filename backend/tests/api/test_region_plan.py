"""Region Plan: a per-region launch plan assembled by code from the brief, the calendar, verdicts, approvals and feedback."""

from datetime import date
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from app.db.base import utcnow
from app.schemas import delivery as d
from app.schemas import desk as desk_schema
from app.services import desk, region_plan
from tests.api.delivery_support import KL, MH, TN, add_asset, add_creative, add_version, approve, campaign_of, compute, review_headers
from tests.api.launch_support import quick_read
from tests.api.omnicult_support import API, add_member, client_for, seeded  # noqa: F401
from tests.api.test_desk import BRIEF_FIXTURE, fixture_brief
from tests.conftest import BOB


async def with_brief(client: httpx.AsyncClient, c: dict[str, Any], **changes: Any) -> None:
    saved = await client.put(f"{c['base']}/brief", json={"content": fixture_brief(**changes), "expected_version": 0})
    assert saved.status_code == 200, saved.text


async def plan_of(client: httpx.AsyncClient, c: dict[str, Any]) -> dict[str, Any]:
    response = await client.get(f"{c['base']}/region-plan")
    assert response.status_code == 200, response.text
    return response.json()


def region(plan: dict[str, Any], code: str) -> dict[str, Any]:
    return next(r for r in plan["regions"] if r["region_code"] == code)


def checks(entry: dict[str, Any]) -> dict[str, tuple[str, str]]:
    return {c["id"]: (c["status"], c["detail"]) for c in entry["checklist"]}


# --- from the brief ---------------------------------------------------------------------------------------------------------


async def test_the_plan_lists_the_brief_regions_with_budget_languages_channels_and_dates(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    await with_brief(client, c)
    plan = await plan_of(client, c)
    assert [r["region_code"] for r in plan["regions"]] == [MH, TN, KL, "IN-WB"] and [r["role"] for r in plan["regions"]] == ["origin", "target", "target", "target"]
    assert (plan["currency"], plan["total_budget"], plan["unallocated_budget"], plan["brief_version"], plan["rule_version"]) == ("INR", 2400000.0, 0.0, 1, "plan-1")
    assert plan["window"] == {"start": "2027-10-04", "end": "2027-11-01", "timezone": "Asia/Kolkata"} and plan["mode"] == "live"
    tn = region(plan, TN)
    assert tn["budget"] == {"currency": "INR", "amount": 600000.0, "share_of_total": 0.25, "sample": False} and tn["languages"] == ["ta", "en"]
    assert [ch["id"] for ch in tn["channels"]] == ["instagram_reels", "youtube_shorts", "meta_feed"]
    assert [e["kind"] for e in tn["timeline"]] == ["campaign_start", "campaign_end"], "Maharashtra's key moments are not Tamil Nadu's"
    mh_moments = [e["title"] for e in region(plan, MH)["timeline"] if e["kind"] == "key_moment"]
    assert mh_moments[0] == "Dhanteras" and len(mh_moments) == 5
    assert plan["source_line"].startswith("Source: campaign brief v1")


async def test_a_campaign_without_a_saved_brief_says_so_and_plans_from_what_is_decided(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    version = await add_version(c)
    await compute(client, c, version)
    plan = await plan_of(client, c)
    assert plan["brief_version"] == 0 and plan["window"] is None and plan["total_budget"] is None
    assert any("No Campaign Brief has been saved" in g for g in plan["gaps"]) and any("names no regions" in g for g in plan["gaps"])
    assert [r["region_code"] for r in plan["regions"]] == [TN]
    assert checks(plan["regions"][0])["dates"][0] == "todo" and checks(plan["regions"][0])["budget"][0] == "todo"


async def test_an_unallocated_budget_is_shown(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    brief = fixture_brief()
    brief["budget"]["by_region"] = {TN: 600000, KL: 400000}
    saved = await client.put(f"{c['base']}/brief", json={"content": brief, "expected_version": 0})
    assert saved.status_code == 200, saved.text
    plan = await plan_of(client, c)
    assert plan["unallocated_budget"] == 1400000.0 and region(plan, MH)["budget"] is None
    assert checks(region(plan, MH))["budget"][0] == "todo" and checks(region(plan, TN))["budget"][0] == "done"


# --- versions, verdicts, approvals ---------------------------------------------------------------------------------------


async def test_a_region_moves_from_candidate_to_ready_as_records_arrive(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    await with_brief(client, c)
    tn = region(await plan_of(client, c), TN)
    assert tn["version"] is None and tn["ready"]["state"] == "not_ready" and tn["pack_available"] is False
    assert checks(tn)["version"][0] == "todo" and checks(tn)["readiness"][0] == "todo" and checks(tn)["approval"][0] == "todo"

    version = await add_version(c)
    tn = region(await plan_of(client, c), TN)
    assert tn["version"]["state"] == "candidate" and tn["version"]["label"] == "Tamil"

    await compute(client, c, version)
    tn = region(await plan_of(client, c), TN)
    assert tn["readiness"]["verdict"] == "go" and checks(tn)["readiness"][0] == "done" and checks(tn)["issues"][0] == "done"
    assert tn["ready"]["state"] == "not_ready" and "No person has approved" in tn["ready"]["reasons"][0]

    await approve(client, c, version)
    tn = region(await plan_of(client, c), TN)
    assert tn["version"]["state"] == "approved" and tn["ready"] == {"state": "ready", "reasons": ["Approved on a Go recommendation."]}
    assert tn["approval"]["decision"] == "approve" and tn["pack_available"] is True and checks(tn)["approval"][0] == "done"
    assert tn["progress_total"] == len(tn["checklist"]) and 0 < tn["progress_done"] < tn["progress_total"]


async def test_an_approval_against_a_fix_recommendation_is_ready_with_override_and_says_why(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    await with_brief(client, c)
    version = await add_version(c)
    await compute(client, c, version, quick_read=quick_read(understood=3, confused=5))
    await approve(client, c, version)
    tn = region(await plan_of(client, c), TN)
    assert tn["readiness"]["verdict"] in ("fix", "rethink") and tn["readiness"]["issues"]
    assert tn["ready"]["state"] == "ready_with_override" and "Reviewed with the regional lead." in tn["ready"]["reasons"][0]
    assert checks(tn)["approval"][0] == "warning" and checks(tn)["issues"][0] in ("warning", "blocked")


async def test_a_rejection_blocks_the_region(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    await with_brief(client, c)
    version = await add_version(c)
    await compute(client, c, version)
    await approve(client, c, version, decision="reject")
    tn = region(await plan_of(client, c), TN)
    assert checks(tn)["approval"][0] == "blocked" and tn["ready"]["state"] == "not_ready" and tn["pack_available"] is False
    assert tn["version"]["state"] == "candidate"


async def test_the_newest_approved_version_is_the_one_planned(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    await with_brief(client, c)
    first, second = await add_version(c, "Tamil v1"), await add_version(c, "Tamil v2")
    await approve(client, c, first)
    assert region(await plan_of(client, c), TN)["version"]["label"] == "Tamil v1"
    await approve(client, c, second)
    assert region(await plan_of(client, c), TN)["version"]["label"] == "Tamil v2"


async def test_rights_confirmed_creative_files_are_counted_per_region(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    await with_brief(client, c)
    ok, draft = await add_asset(c, filename="ok.png"), await add_asset(c, filename="draft.png", rights=False)
    await add_creative(c, ok, label="Tamil visual", region=TN)
    await add_creative(c, draft, label="Kerala draft", region=KL)
    plan = await plan_of(client, c)
    assert checks(region(plan, TN))["creatives"] == ("done", "1 file can go in the pack.")
    assert checks(region(plan, KL))["creatives"][0] == "warning" and checks(region(plan, "IN-WB"))["creatives"][0] == "todo"


async def test_stakeholder_feedback_is_shown_beside_the_plan_and_never_counts_as_approval(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    await with_brief(client, c)
    version = await add_version(c)
    await compute(client, c, version)
    link = (await client.post(f"{c['base']}/review-links", json={"label": "Agency", "items": [{"version_id": str(version), "region_code": TN}]})).json()
    for decision, extra in (("approve", {}), ("request_changes", {"comment": "Rework the call to action."})):
        sent = await client.post(f"{API}/review/responses", headers=review_headers(link["token"]),
                                 json={"version_id": str(version), "region_code": TN, "decision": decision} | extra)
        assert sent.status_code == 201, sent.text
    tn = region(await plan_of(client, c), TN)
    assert tn["feedback"]["counts"] == {"approve": 1, "request_changes": 1, "reject": 0, "comment": 0} and tn["feedback"]["latest_at"]
    assert any("asked for changes" in w for w in tn["warnings"])
    assert tn["ready"]["state"] == "not_ready" and tn["approval"] is None and tn["version"]["state"] == "candidate"


# --- dates ---------------------------------------------------------------------------------------------------------------------


def brief_with(moments: list[dict[str, Any]], **dates: Any) -> desk_schema.BriefContent:
    content = desk.brief_from_fixture(BRIEF_FIXTURE).model_dump(mode="json")
    content["dates"]["key_moments"] = moments
    content["dates"] |= dates
    return desk_schema.BriefContent.model_validate(content)


def moment(name: str, day: str, regions: list[str] | None = None, sources: list[str] | None = None) -> dict[str, Any]:
    return {"id": name.lower().replace(" ", "-"), "name": name, "date": day, "region_codes": regions if regions is not None else [MH],
            "source_ids": sources if sources is not None else ["astrosage-diwali-2027"]}


def test_a_key_moment_outside_the_window_without_a_source_or_on_the_same_day_is_flagged() -> None:
    content = brief_with([moment("Early festival", "2027-09-20"), moment("No source", "2027-10-10", sources=[]), moment("Twin A", "2027-10-20"),
                          moment("Twin B", "2027-10-20"), moment("Fine", "2027-10-25")])
    events, warnings = region_plan.timeline_for(MH, content, [])
    by_title = {e.title: e for e in events}
    assert "outside the campaign dates" in by_title["Early festival"].warning and "No source is cited" in by_title["No source"].warning
    assert "Same day as Twin B" in by_title["Twin A"].warning and by_title["Fine"].warning is None
    assert len(warnings) == 4 and [e.date for e in events] == sorted(e.date for e in events)
    assert [e.kind for e in events if e.kind.startswith("campaign")] == ["campaign_start", "campaign_end"] and events[0].title == "Early festival"


def test_a_moment_that_names_no_region_applies_to_every_region_and_calendar_moments_do_not_repeat_the_brief() -> None:
    content = brief_with([moment("Diwali", "2027-10-29", regions=[]), moment("Local", "2027-10-12", regions=[KL])])
    events, _ = region_plan.timeline_for(TN, content, [(date(2027, 10, 29), "Diwali (public holiday)", "Moment Calendar"), (date(2027, 10, 20), "Tamil festival", "Moment Calendar")])
    assert [(e.title, e.kind) for e in events] == [
        ("Campaign starts", "campaign_start"), ("Tamil festival", "calendar_moment"), ("Diwali", "key_moment"), ("Campaign ends", "campaign_end")]


def test_without_dates_there_is_no_timeline() -> None:
    content = desk.brief_from_fixture(BRIEF_FIXTURE).model_copy(update={"dates": None})
    assert region_plan.timeline_for(MH, content, []) == ([], [])


def approval(decision: str = "approve", override: bool = False) -> d.PlanApproval:
    return d.PlanApproval(id=uuid4(), decision=decision, decided_by_name="Asha", decided_at=utcnow(), reason="Because.",  # type: ignore[arg-type]
                          verdict_at_decision="fix" if override else "go", overrides_recommendation=override)


def readiness(verdict: str) -> d.PlanReadiness:
    return d.PlanReadiness(verdict=verdict, main_reason="Reason.", next_action="Act.", computed_at=utcnow(), rule_version="ready-1", issues=[])  # type: ignore[arg-type]


def test_ready_needs_an_approval_on_a_go_recommendation() -> None:
    assert region_plan.ready_state(None, readiness("go")).state == "not_ready"
    assert region_plan.ready_state(approval("reject"), readiness("go")).state == "not_ready"
    assert region_plan.ready_state(approval(), readiness("go")).state == "ready"
    assert region_plan.ready_state(approval(override=True), readiness("fix")).state == "ready_with_override"
    assert region_plan.ready_state(approval(override=True), None).state == "ready_with_override"


# --- exports and access ------------------------------------------------------------------------------------------------


async def test_the_plan_exports_as_markdown_and_pdf_with_the_proof_export_code(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    await with_brief(client, c)
    version = await add_version(c)
    await compute(client, c, version)
    await approve(client, c, version)
    md = await client.get(f"{c['base']}/region-plan/export", params={"format": "markdown"})
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert md.headers["content-disposition"].startswith('attachment; filename="omnicult-region-plan-') and md.headers["content-disposition"].endswith('.md"')
    text = md.text
    assert text.startswith("# Region Plan: ") and "## Tamil Nadu (IN-TN)" in text and "### Checklist" in text and "### Timeline" in text
    assert "| Tamil Nadu (IN-TN) | target | Tamil (approved) | Go | approve | INR 600,000 | ready | " in text
    assert "no model was called" in text and "—" not in text
    pdf = await client.get(f"{c['base']}/region-plan/export")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and pdf.headers["content-type"] == "application/pdf"
    assert (await client.get(f"{c['base']}/region-plan/export", params={"format": "docx"})).status_code == 422


async def test_any_member_reads_the_plan_and_a_stranger_cannot(client_for: Any, client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    await with_brief(client, c)
    await add_member(UUID(c["workspace_id"]), "bob", "viewer")
    assert (await client_for(BOB).get(f"{c['base']}/region-plan")).status_code == 200
    assert (await client_for(BOB).get(f"{c['base']}/region-plan/export")).status_code == 200
    stranger = client_for({"Authorization": "Bearer dev-stranger"})
    assert (await stranger.get(f"{c['base']}/region-plan")).status_code == 404
    assert (await stranger.get(f"{c['base']}/region-plan/export")).status_code == 404
    assert (await client.get(f"{API}/campaigns/{uuid4()}/region-plan")).status_code == 404
