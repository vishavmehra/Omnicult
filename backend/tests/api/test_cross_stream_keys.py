"""The cross-stream foreign keys of migration 0021, enforced by the database (the test engine turns foreign keys on, as the
application does): a record can only point at a parent of its own campaign or project, and a parent that records point at
cannot be deleted. Each case has a positive control, so a refusal means the key and not a malformed row."""

from datetime import date
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from tests.api.glue_support import add_creative, add_transcreation, root_version
from tests.api.omnicult_support import seeded  # noqa: F401
from tests.api.proof_support import add_run, campaign_with_regions


async def world(client: httpx.AsyncClient) -> dict[str, Any]:
    """A campaign with a Creative Studio version, a transcreate operation, a creative, a verdict row and a campaign content version."""
    base = await campaign_with_regions(client)
    cid, pid = base["campaign"]["id"], base["project"]["id"]
    node = await root_version(client, cid)
    op, ai_node = await add_transcreation(cid, pid, node["id"], [])
    creative, _ = await add_creative(cid, pid)
    async with read_session() as s:
        content = await s.scalar(select(m.CampaignVersion.id).where(m.CampaignVersion.campaign_id == UUID(cid)))
        region = await s.scalar(select(m.Region.id).where(m.Region.code == "IN-TN"))
    me = UUID((await client.get("/api/v1/me")).json()["id"])
    return {"cid": UUID(cid), "pid": UUID(pid), "node": UUID(node["id"]), "op": op, "ai_node": ai_node, "creative": creative,
            "content": content, "region": region, "me": me}


async def write(*rows: Any) -> None:
    async with session() as s, s.begin():
        s.add_all(rows)


async def refused(*rows: Any) -> None:
    with pytest.raises(IntegrityError):
        await write(*rows)


def verdict(w: dict[str, Any], version: UUID) -> m.ReadinessVerdict:
    return m.ReadinessVerdict(
        id=uuid4(), project_id=w["pid"], campaign_id=w["cid"], region_id=w["region"], version_id=version, verdict="go", main_reason="r",
        rule_version="ready-1", scoring_version="mvp-2", input_fingerprint=uuid4().hex, inputs={}, result={}, mode="live",
        computed_by=w["me"], computed_at=utcnow())


def approval(w: dict[str, Any], version: UUID) -> m.Approval:
    return m.Approval(
        id=uuid4(), project_id=w["pid"], campaign_id=w["cid"], region_id=w["region"], version_id=version, decision="approve", reason="ok",
        overrides_recommendation=False, mode="live", decided_by=w["me"], decided_at=utcnow())


def chip(w: dict[str, Any], **applied: Any) -> m.Chip:
    return m.Chip(
        id=uuid4(), campaign_id=w["cid"], project_id=w["pid"], version_id=w["node"], element_id="headline", title="t",
        operation_type="replace_text", change={"value": "x"}, reason="r", expected_effect="e", **applied)


async def test_a_verdict_or_approval_must_point_at_a_creative_version_of_its_own_campaign(seeded: Any, client: httpx.AsyncClient) -> None:
    a, b = await world(client), await world(client)
    await write(verdict(a, a["node"]), approval(a, a["node"]))  # control
    for version in (uuid4(), b["node"], a["content"]):  # an invented id, another campaign's version, a campaign content version
        await refused(verdict(a, version))
        await refused(approval(a, version))


async def test_a_version_that_a_verdict_points_at_cannot_be_deleted(seeded: Any, client: httpx.AsyncClient) -> None:
    w = await world(client)
    await write(verdict(w, w["node"]))
    with pytest.raises(IntegrityError):  # RESTRICT: the record stays, so the version stays
        async with session() as s, s.begin():
            await s.delete(await s.get(m.VersionNode, w["node"]))


async def test_an_applied_chip_must_point_at_its_own_operation_and_version(seeded: Any, client: httpx.AsyncClient) -> None:
    a, b = await world(client), await world(client)
    await write(chip(a, applied_operation_id=a["op"], applied_version_id=a["ai_node"], status="applied"))  # control
    await refused(chip(a, applied_operation_id=uuid4()))
    await refused(chip(a, applied_version_id=b["ai_node"]))
    await refused(chip(a, applied_version_id=uuid4()))


async def test_a_creative_can_only_point_at_runs_of_its_own_project(seeded: Any, client: httpx.AsyncClient) -> None:
    a, b = await world(client), await world(client)
    own, foreign = await add_run(str(a["pid"]), str(a["cid"]), run_type="creative_xray"), await add_run(str(b["pid"]), str(b["cid"]), run_type="creative_xray")
    for column in ("latest_run_id", "current_run_id"):
        async with session() as s, s.begin():  # control
            setattr(await s.get(m.CreativeAsset, a["creative"]), column, own)
        with pytest.raises(IntegrityError):
            async with session() as s, s.begin():
                setattr(await s.get(m.CreativeAsset, a["creative"]), column, foreign)
        with pytest.raises(IntegrityError):
            async with session() as s, s.begin():
                setattr(await s.get(m.CreativeAsset, a["creative"]), column, uuid4())


def audience_run(w: dict[str, Any], content: UUID | None) -> m.AudienceRun:
    return m.AudienceRun(
        id=uuid4(), project_id=w["pid"], campaign_id=w["cid"], kind="quick_read", status="completed", mode="live",
        content_version_id=content, config={}, inputs={}, steps=[], created_at=utcnow())


def report(w: dict[str, Any], content: UUID | None) -> m.ProofReport:
    return m.ProofReport(
        id=uuid4(), project_id=w["pid"], campaign_id=w["cid"], campaign_version_id=content, version_number=1, title="t", status="partial",
        mode="live", content_sha256="0" * 64, content={})


async def test_runs_and_reports_can_only_name_a_content_version_of_their_own_campaign(seeded: Any, client: httpx.AsyncClient) -> None:
    a, b = await world(client), await world(client)
    await write(audience_run(a, a["content"]), audience_run(a, None), report(a, a["content"]))  # controls; no version is allowed too
    for content in (b["content"], uuid4()):
        await refused(audience_run(a, content))
        await refused(report(a, content))


async def test_metric_rows_must_belong_to_the_project_of_their_campaign(seeded: Any, client: httpx.AsyncClient) -> None:
    a, b = await world(client), await world(client)

    def row(project: UUID) -> m.MetricSeries:
        return m.MetricSeries(
            id=uuid4(), workspace_id=None, project_id=project, campaign_id=a["cid"], day=date(2026, 11, 1), platform="meta", channel="feed",
            version_label="A", region_code="IN-TN", metric="impressions", value=1.0, source_kind="sample", dataset_version="v1",
            last_updated_at=utcnow())

    await write(row(a["pid"]))  # control
    await refused(row(b["pid"]))  # alice's campaign, another project: the single-column keys alone would accept it
