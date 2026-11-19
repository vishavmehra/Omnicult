"""Weekly Digest API: generated from stored records by code, one per ISO week, exported through the Proof exporters."""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.core.auth import dev_user_id
from app.core.config import get_settings
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.fixtures import pulse_comments as comment_sample
from app.llm.fixture import FixtureLLMProvider
from app.llm.gateway import LLMGateway
from app.schemas import digest as dv
from app.services import digest as digest_service
from app.services.comment_pulse import flags_of
from app.services import pulse_sample as pulse_data
from app.services import studio_context
from tests.api.omnicult_support import API, add_member, all_claims, client_for, draft, put_claims, seeded, source, workspace_of  # noqa: F401
from tests.api.test_crud import make_campaign, make_project
from tests.conftest import BOB

NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)  # a Wednesday; 14:30 in India
WEEK_OF = "2026-11-12"  # inside ISO week 2026-W46: Monday 9 November to Sunday 15 November
ORIGINAL, ADAPTED_A = pulse_data.ORIGINAL, pulse_data.ADAPTED_A


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> datetime:
    monkeypatch.setattr(digest_service, "utcnow", lambda: NOW)
    return NOW


async def campaign_of(client: httpx.AsyncClient, *, demo: bool) -> tuple[dict[str, Any], str]:
    if demo:
        project = (await client.post(f"{API}/projects/demo")).json()
        campaign = (await client.get(f"{API}/projects/{project['id']}/campaigns")).json()["items"][0]
    else:
        project = await make_project(client)
        campaign = await make_campaign(client, project["id"])
    return project, campaign["id"]


async def prepared(client: httpx.AsyncClient, *, demo: bool = True, read: bool = True) -> str:
    """A campaign with the Pulse sample, the sample comments and (in a demo project) the fixture reading of them."""
    _, cid = await campaign_of(client, demo=demo)
    assert (await client.post(f"{API}/campaigns/{cid}/pulse/sample-dataset")).status_code == 200
    assert (await client.post(f"{API}/campaigns/{cid}/pulse/comments/sample")).status_code == 200
    if read:
        assert (await client.post(f"{API}/campaigns/{cid}/pulse/comments/read")).status_code == 200
    return cid


async def generate(client: httpx.AsyncClient, cid: str, **body: Any) -> dict[str, Any]:
    response = await client.post(f"{API}/campaigns/{cid}/pulse/digests", json={"week_of": WEEK_OF} | body)
    assert response.status_code == 200, response.text
    return response.json()


def scripted_summary(responder: Callable[[dict[str, Any]], Any], monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    class Provider(FixtureLLMProvider):
        name = "scripted"

    def answer(ctx: Any) -> Any:
        seen.append(dict(ctx))
        return responder(dict(ctx))

    provider = Provider({"digest-summary-v1": answer})
    monkeypatch.setattr(studio_context, "gateway_for", lambda mode: LLMGateway(get_settings(), provider=provider, backoff_seconds=0))
    return seen


def raw_ctr(region: str, version: str, first: date, last: date) -> float:
    """CTR of a slice over settled days, from the generator's raw rows (independent of the service's own code)."""
    clicks = impressions = 0.0
    for r in pulse_data.generate_sample_rows():
        if r.region_code == region and r.version_label == version and first <= r.day <= last and not r.provisional:
            clicks += r.value if r.metric == "clicks" else 0
            impressions += r.value if r.metric == "impressions" else 0
    return clicks / impressions


# --- Pulse movement and alerts ----------------------------------------------------------------------------------------


async def test_pulse_movement_compares_the_last_settled_week_with_the_week_before(client: httpx.AsyncClient, clock: datetime) -> None:
    cid = await prepared(client)
    created = await generate(client, cid)
    assert created["created"] is True
    content = created["digest"]["content"]
    assert content["week"] == {"iso_year": 2026, "iso_week": 46, "label": "2026-W46", "start": "2026-11-09", "end": "2026-11-15", "timezone": "Asia/Kolkata"}
    pulse = content["pulse"]
    # the week ends on Sunday 15 November, but 15 and 16 November are provisional: the data window ends on Saturday the 14th
    assert pulse["available"] is True and pulse["settled_through"] == "2026-11-14" and pulse["provisional_days_excluded"] == 1
    assert (pulse["window_from"], pulse["window_to"], pulse["previous_from"], pulse["previous_to"]) == ("2026-11-08", "2026-11-14", "2026-11-01", "2026-11-07")
    assert len(pulse["slices"]) == 10
    kl = next(s for s in pulse["slices"] if s["region_code"] == "IN-KL" and s["version_label"] == ORIGINAL)
    ctr = next(x for x in kl["metrics"] if x["metric"] == "ctr")
    now_ctr = raw_ctr("IN-KL", ORIGINAL, date(2026, 11, 8), date(2026, 11, 14))
    before_ctr = raw_ctr("IN-KL", ORIGINAL, date(2026, 11, 1), date(2026, 11, 7))
    assert ctr["current"] == pytest.approx(now_ctr) and ctr["previous"] == pytest.approx(before_ctr)
    assert ctr["delta"] == pytest.approx(now_ctr - before_ctr) and ctr["delta_pct"] == pytest.approx(now_ctr / before_ctr - 1)
    assert ctr["delta_pct"] < -0.1, "the wearing-out Kerala original is the sample's story"
    assert [x["metric"] for x in kl["metrics"]] == ["impressions", "spend", "ctr", "cpm", "cpa", "roas"]
    assert pulse["source"] == ""  # no origin disclaimer reaches the UI

    # the alerts are the preview's rules run over the data up to that day: the same alerts the dashboard shows
    preview = (await client.get(f"{API}/campaigns/{cid}/pulse/alerts")).json()
    assert {(a["alert_type"], a["region_code"], a["version_label"]) for a in pulse["alerts"]} == {
        (a["alert_type"], a["region_code"], a["version_label"]) for a in preview["alerts"]} and pulse["alerts"]
    assert all(a["headline"] and a["suggested_action"] and f"/campaigns/{cid}/pulse/timeseries" in a["source_path"] for a in pulse["alerts"])


async def test_the_first_week_has_no_earlier_period_to_compare(client: httpx.AsyncClient, clock: datetime) -> None:
    cid = await prepared(client)
    # W45 (2-8 November): the week before it would be 26 October to 1 November, but the data starts on the 27th, so there is no full week to compare
    second = (await generate(client, cid, week_of="2026-11-04"))["digest"]["content"]["pulse"]
    assert (second["window_from"], second["window_to"], second["previous_from"], second["previous_to"]) == ("2026-11-02", "2026-11-08", None, None)
    # W44 (26 October to 1 November): only 27 October to 1 November is on file, a partial week, shown without a comparison
    early = (await generate(client, cid, week_of="2026-10-28"))["digest"]["content"]["pulse"]
    assert early["available"] is True and early["window_to"] == "2026-11-01" and early["window_from"] == "2026-10-27" and early["previous_from"] is None
    for pulse in (second, early):
        assert all(x["previous"] is None and x["delta"] is None and x["delta_pct"] is None for s in pulse["slices"] for x in s["metrics"])
        assert all(x["current"] is not None for s in pulse["slices"] for x in s["metrics"] if x["metric"] in ("impressions", "ctr"))


async def test_a_week_before_the_data_says_so(client: httpx.AsyncClient, clock: datetime) -> None:
    cid = await prepared(client)
    pulse = (await generate(client, cid, week_of="2026-10-14"))["digest"]["content"]["pulse"]
    assert pulse["available"] is False and "settled" in pulse["reason"] and pulse["slices"] == [] and pulse["alerts"] == []


# --- comments in the digest ------------------------------------------------------------------------------------------


async def test_the_comments_section_counts_the_data_window_and_quotes_stored_comments(client: httpx.AsyncClient, clock: datetime) -> None:
    cid = await prepared(client)
    content = (await generate(client, cid))["digest"]["content"]
    section = content["comments"]
    window = [c for c in comment_sample.generate_comments() if date(2026, 11, 8) <= c.day <= date(2026, 11, 14)]
    assert section["available"] is True and section["comments_total"] == 88 and section["comments_in_window"] == len(window)
    assert (section["window_from"], section["window_to"]) == ("2026-11-08", "2026-11-14")
    assert section["sentiment"] is not None and sum(section["sentiment"][k] for k in ("positive", "neutral", "negative", "mixed")) == len(window)
    kinds = [{f.kind for f in flags_of(c.text)} for c in window]
    assert section["claim_mentions_in_window"] == sum("planted_claim" in k for k in kinds)
    assert section["cultural_mentions_in_window"] == sum("cultural_misstep" in k for k in kinds)
    texts = {c.text for c in comment_sample.generate_comments()}
    assert len(section["themes"]) <= 3 and all(t["label"] and t["summary"] for t in section["themes"])
    assert all(t["quote"] is None or t["quote"]["text"] in texts for t in section["themes"])
    assert all(f["text"] in texts and f["source"] == {"workspace": "pulse", "view": "comments", "ref": f["ref"]} for f in section["flagged"])
    assert len(section["flagged"]) <= 6 and [f["likes"] for f in section["flagged"]] == sorted((f["likes"] for f in section["flagged"]), reverse=True)


async def test_comment_mentions_become_next_actions(client: httpx.AsyncClient, clock: datetime) -> None:
    cid = await prepared(client)
    rules: set[str] = set()
    texts: list[str] = []
    for day in ("2026-10-28", "2026-11-04", "2026-11-11"):  # the three weeks of the sample run
        content = (await generate(client, cid, week_of=day))["digest"]["content"]
        rules |= {a["rule"] for a in content["next_actions"]}
        texts += [a["text"] for a in content["next_actions"] if a["rule"].startswith("comment_")]
    assert {"pulse_alert", "comment_claim_mentions", "comment_festival_mentions"} <= rules
    assert any("best faral tin" in t for t in texts) and any("Kerala" in t or "West Bengal" in t for t in texts)
    assert len((await client.get(f"{API}/campaigns/{cid}/pulse/digests")).json()["items"]) == 3


async def test_without_a_reading_the_digest_has_counts_but_no_sentiment_or_themes(client: httpx.AsyncClient, clock: datetime) -> None:
    cid = await prepared(client, read=False)
    section = (await generate(client, cid))["digest"]["content"]["comments"]
    assert section["available"] is True and section["sentiment"] is None and section["themes"] == [] and section["comments_in_window"] > 0


# --- storing, idempotence, regeneration -------------------------------------------------------------------------------


async def test_one_digest_per_week_and_a_regeneration_bumps_the_revision(client: httpx.AsyncClient, clock: datetime) -> None:
    cid = await prepared(client)
    first = await generate(client, cid)
    assert first["created"] is True and first["digest"]["revision"] == 1 and first["digest"]["trigger"] == "manual"
    again = await generate(client, cid, week_of="2026-11-10")  # any date in the same ISO week
    assert again["created"] is False and again["digest"]["id"] == first["digest"]["id"] and again["digest"] == first["digest"]
    redone = await generate(client, cid, regenerate=True)
    assert redone["created"] is True and redone["digest"]["id"] == first["digest"]["id"] and redone["digest"]["revision"] == 2
    assert redone["digest"]["content_sha256"] == first["digest"]["content_sha256"], "equal records and clock give an equal hash"
    other = await generate(client, cid, week_of="2026-11-03")
    assert other["digest"]["id"] != first["digest"]["id"] and other["digest"]["content"]["week"]["label"] == "2026-W45"
    listing = (await client.get(f"{API}/campaigns/{cid}/pulse/digests")).json()
    assert [i["week"]["label"] for i in listing["items"]] == ["2026-W46", "2026-W45"]
    assert listing["current_week"]["label"] == "2026-W47" and listing["narrative_available"] is False  # a demo project
    assert listing["items"][0]["revision"] == 2 and listing["items"][0]["has_narrative"] is False
    got = (await client.get(f"{API}/campaigns/{cid}/pulse/digests/{first['digest']['id']}")).json()
    assert got["content"] == redone["digest"]["content"]
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.PulseDigest)) == 2
        actions = set(await s.scalars(select(m.AuditLog.action).where(m.AuditLog.action.like("pulse.digest%"))))
        assert actions == {"pulse.digest.generate"}


async def test_a_future_week_is_refused(client: httpx.AsyncClient, clock: datetime) -> None:
    cid = await prepared(client)
    response = await client.post(f"{API}/campaigns/{cid}/pulse/digests", json={"week_of": "2026-11-23"})
    assert response.status_code == 422 and response.json()["error"]["details"][0]["field"] == "week_of"
    this_week = await client.post(f"{API}/campaigns/{cid}/pulse/digests", json={})
    assert this_week.status_code == 200 and this_week.json()["digest"]["content"]["week"]["label"] == "2026-W47"
    assert (await client.post(f"{API}/campaigns/{cid}/pulse/digests")).json()["created"] is False, "the body is optional"


async def test_a_digest_of_an_empty_campaign_says_what_is_missing_instead_of_failing(client: httpx.AsyncClient, clock: datetime) -> None:
    _, cid = await campaign_of(client, demo=False)
    content = (await generate(client, cid))["digest"]["content"]
    assert content["pulse"]["available"] is False and "No Live Pulse data" in content["pulse"]["reason"]
    assert content["comments"]["available"] is False and content["comments"]["themes"] == []
    assert sum(content["what_changed"]["counts"].values()) == 0
    assert [a["rule"] for a in content["next_actions"]] == ["no_pulse_data"]
    assert content["limitations"] and content["mode"] == "live"


# --- what changed and what is open ------------------------------------------------------------------------------------


async def test_what_changed_and_open_items_come_from_stored_records(seeded: Any, client: httpx.AsyncClient) -> None:
    project, cid = await campaign_of(client, demo=False)
    alice, workspace = dev_user_id("alice"), await workspace_of("alice")
    root = (await client.post(f"{API}/campaigns/{cid}/versions", json={
        "label": "Original", "region_code": "IN-MH", "language": "mr",
        "elements": [{"id": "headline", "kind": "headline", "value": "x", "language": "mr", "script": "Deva"}]})).json()
    async with read_session() as s:
        regions = {r.code: r for r in (await s.execute(select(m.Region))).scalars()}
    async with session() as s, s.begin():
        campaign = await s.get(m.Campaign, UUID(cid))
        campaign.target_markets = [{"country_code": "IN", "display_name": "Tamil Nadu", "region_code": "IN-TN"}]
        s.add(m.ReadinessVerdict(
            id=uuid4(), project_id=UUID(project["id"]), campaign_id=UUID(cid), region_id=regions["IN-TN"].id, version_id=UUID(root["id"]),
            verdict="rethink", main_reason="The festival named in the copy is not sourced for this region.", rule_version="r1",
            scoring_version="s1", overall_score=None, input_fingerprint="f", inputs={}, result={}, mode="live", computed_by=alice))
        run = m.AudienceRun(
            id=uuid4(), workspace_id=workspace, project_id=UUID(project["id"]), campaign_id=UUID(cid), kind="risk_check",
            status="completed", mode="live", region_codes=["IN-TN"], version_ref=root["id"], config={}, inputs={})
        s.add(run)
        await s.flush()
        for n, (severity, blocks) in enumerate((("low", False), ("high", True), ("medium", False))):
            s.add(m.RiskFindingRow(
                id=uuid4(), run_id=run.id, ordinal=n, element_id=f"e{n}", category="regional_sensitivity", severity=severity,
                blocks_go=blocks, confidence_label="limited", anchor={}, verification="deterministic",
                observation=f"Observation {n}", interpretation="It may read differently.", source="deterministic_check",
                rules_version="risk-rules-v1"))
    await put_claims(workspace, [
        draft("a", attribute="first_festival", region="IN-TN", text="Festival A", sources=[source("wikimedia")]),
        draft("b", attribute="second_festival", region="IN-TN", text="Festival B", sources=[source("wikimedia")])])
    claims = await all_claims()
    async with session() as s, s.begin():
        s.add(m.Conflict(
            id=uuid4(), workspace_id=workspace, region_id=regions["IN-TN"].id, claim_a_id=claims[0].id, claim_b_id=claims[1].id,
            reason="Two sources name a different main festival.", current_selection="a", selection_reason="Newest source.", status="open"))

    content = (await client.post(f"{API}/campaigns/{cid}/pulse/digests", json={})).json()["digest"]["content"]
    changed = content["what_changed"]
    assert changed["counts"]["creative_versions"] == 1 and changed["counts"]["risk_findings"] == 3 and changed["counts"]["audience_runs"] == 1
    assert changed["counts"]["verdicts"] == 1 and changed["counts"]["conflicts_opened"] == 1
    assert changed["versions"][0]["label"] == "Original" and changed["versions"][0]["source"] == {"workspace": "studio", "view": None, "ref": root["id"]}
    assert changed["verdicts"][0]["verdict"] == "rethink" and changed["verdicts"][0]["region_code"] == "IN-TN" and changed["verdicts"][0]["version_label"] == "Original"
    assert {(r["kind"], r["status"]) for r in changed["runs"]} == {("audience:risk_check", "completed")}
    items = content["open_items"]
    assert [n["region_code"] for n in items["not_ready"]] == ["IN-TN"] and items["conflicts_total"] == 1 and items["conflicts"][0]["region_code"] == "IN-TN"
    assert items["risk_findings_total"] == 3 and [f["severity"] for f in items["risk_findings"]] == ["high", "medium", "low"], "blocking first, then by severity"
    actions = content["next_actions"]
    assert [a["priority"] for a in actions] == sorted(a["priority"] for a in actions)
    assert [a["rule"] for a in actions][:2] == ["readiness_not_go", "risk_blocks_go"] and actions[0]["text"].startswith("Rethink the Tamil Nadu version")
    assert actions[0]["why"] == "The festival named in the copy is not sourced for this region." and actions[0]["source"]["workspace"] == "launch"
    assert "conflict_open" in {a["rule"] for a in actions} and actions[-1]["rule"] == "no_pulse_data"


# --- export ---------------------------------------------------------------------------------------------------------


async def test_export_markdown_and_pdf_reuse_the_proof_exporters(client: httpx.AsyncClient, clock: datetime) -> None:
    cid = await prepared(client)
    digest = (await generate(client, cid))["digest"]
    url = f"{API}/campaigns/{cid}/pulse/digests/{digest['id']}/export"
    md = await client.get(url + "?format=md")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert md.headers["content-disposition"] == 'attachment; filename="omnicult-digest-2026-W46.md"' and md.headers["cache-control"] == "private, no-store"
    text = md.text
    for heading in ("# Weekly digest:", "## What changed", "## Pulse movement and alerts", "## Comments", "## Open conflicts and issues",
                    "## Next actions", "## Limitations"):
        assert heading in text, heading
    kl = next(s for s in digest["content"]["pulse"]["slices"] if s["region_code"] == "IN-KL" and s["version_label"] == ORIGINAL)
    ctr = next(x for x in kl["metrics"] if x["metric"] == "ctr")
    assert f"{ctr['current'] * 100:.2f}% ({ctr['delta_pct'] * 100:+.1f}%)" in text, "the exported figures are the stored ones"
    assert "Theme (Model interpretation)" in text and "sample dataset" not in text
    assert any(ord(ch) > 0x900 for ch in text), "Indic comments stay in their own script in Markdown"
    assert (await client.get(url + "?format=md")).text == text, "an export of equal records is equal"
    pdf = await client.get(url + "?format=pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert pdf.headers["content-disposition"] == 'attachment; filename="omnicult-digest-2026-W46.pdf"'
    assert (await client.get(url + "?format=docx")).status_code == 422
    assert (await client.get(f"{API}/campaigns/{cid}/pulse/digests/{uuid4()}/export")).status_code == 404


# --- the optional model summary -----------------------------------------------------------------------------------------


async def test_a_summary_is_kept_only_when_every_number_in_it_is_in_the_digest(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, clock: datetime) -> None:
    cid = await prepared(client, demo=False, read=False)
    digest = (await generate(client, cid))["digest"]
    url = f"{API}/campaigns/{cid}/pulse/digests/{digest['id']}/summary"
    assert (await client.get(f"{API}/campaigns/{cid}/pulse/digests")).json()["narrative_available"] is True

    seen = scripted_summary(lambda ctx: {"summary": "Overview: " + " ".join(ctx["facts"][:2])}, monkeypatch)
    done = await client.post(url)
    assert done.status_code == 200, done.text
    narrative = done.json()["narrative"]
    assert narrative["label"] == "Model interpretation" and narrative["provider"] == "scripted" and narrative["prompt_version"] == "digest-summary-v1"
    assert narrative["text"].startswith("Overview: Week 2026-W46") and len(seen) == 1
    assert done.json()["content"] == digest["content"] and done.json()["content_sha256"] == digest["content_sha256"], "the summary never touches the numbers"
    assert (await client.get(f"{API}/campaigns/{cid}/pulse/digests")).json()["items"][0]["has_narrative"] is True
    md = (await client.get(f"{API}/campaigns/{cid}/pulse/digests/{digest['id']}/export?format=md")).text
    assert "## Summary (Model interpretation)" in md and narrative["text"] in md

    scripted_summary(lambda ctx: {"summary": "The campaign gained 48213 new followers and doubled its reach this week."}, monkeypatch)
    bad = await client.post(url)
    assert bad.status_code == 502 and "48213" in bad.json()["error"]["message"] and "discarded" in bad.json()["error"]["message"]
    assert (await client.get(f"{API}/campaigns/{cid}/pulse/digests/{digest['id']}")).json()["narrative"]["text"] == narrative["text"], "the old summary is kept"

    redone = await generate(client, cid, regenerate=True)
    assert redone["digest"]["narrative"] is None, "a regenerated week drops a summary written for the old numbers"


async def test_a_demo_project_has_no_model_summary(client: httpx.AsyncClient, clock: datetime) -> None:
    cid = await prepared(client)
    digest = (await generate(client, cid))["digest"]
    response = await client.post(f"{API}/campaigns/{cid}/pulse/digests/{digest['id']}/summary")
    assert response.status_code == 409 and "live projects only" in response.json()["error"]["message"]


# --- access ---------------------------------------------------------------------------------------------------------


async def test_another_workspace_gets_404_and_a_viewer_can_read_but_not_generate(client: httpx.AsyncClient, client_for: Any, clock: datetime) -> None:
    cid = await prepared(client)
    digest = (await generate(client, cid))["digest"]
    base = f"{API}/campaigns/{cid}/pulse/digests"
    stranger = client_for(BOB)
    assert (await stranger.get(base)).status_code == 404
    assert (await stranger.post(base, json={"week_of": WEEK_OF})).status_code == 404
    assert (await stranger.get(f"{base}/{digest['id']}")).status_code == 404
    assert (await stranger.get(f"{base}/{digest['id']}/export")).status_code == 404
    assert (await stranger.post(f"{base}/{digest['id']}/summary")).status_code == 404
    await add_member(await workspace_of("alice"), "viewer-vic", "viewer")
    viewer = client_for({"Authorization": "Bearer dev-viewer-vic"})
    assert (await viewer.get(f"{base}/{digest['id']}")).status_code == 200
    assert (await viewer.get(f"{base}/{digest['id']}/export?format=md")).status_code == 200
    assert (await viewer.post(base, json={"week_of": WEEK_OF, "regenerate": True})).status_code == 403
    _, other = await campaign_of(client, demo=False)
    assert (await client.get(f"{base}/{digest['id']}".replace(cid, other))).status_code == 404, "a digest belongs to its own campaign"


async def test_the_digest_is_built_without_a_model_a_provider_or_the_network(client: httpx.AsyncClient, clock: datetime, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = await prepared(client, demo=False, read=False)

    def refuse(mode: str) -> Any:
        raise AssertionError("generating a digest must not call a model")

    monkeypatch.setattr(studio_context, "gateway_for", refuse)
    assert (await generate(client, cid))["digest"]["narrative"] is None
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.AiUsageEvent)) == 0


def test_the_week_helpers_use_india_standard_time() -> None:
    from app.services.digest_build import current_week, last_completed_week, week_bounds, week_of

    sunday_night_utc = datetime(2026, 11, 15, 18, 30, tzinfo=UTC)  # Monday 00:00 in India
    assert current_week(sunday_night_utc).label == "2026-W47" and last_completed_week(sunday_night_utc).label == "2026-W46"
    assert current_week(sunday_night_utc - timedelta(minutes=1)).label == "2026-W46"
    lo, hi = week_bounds(week_of(date(2026, 11, 12)))
    assert lo == datetime(2026, 11, 8, 18, 30, tzinfo=UTC) and hi - lo == timedelta(days=7)
    assert week_of(date(2026, 12, 31)).label == "2026-W53" and week_of(date(2027, 1, 3)).label == "2026-W53" and week_of(date(2027, 1, 4)).label == "2027-W01"
