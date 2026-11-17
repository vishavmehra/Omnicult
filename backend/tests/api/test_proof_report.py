"""Proof Report v2: registered sections, missing sections, kind labels, snapshots, exports, and workspace isolation."""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from app.core.auth import dev_user_id
from app.core.config import get_settings
from app.db import blobs
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas.proof import SECTION_MODELS
from app.services import proof_sections
from app.services.proof_sections import NOT_IN_BUILD, REGISTRY, Missing, Provided, SectionContext, assemble, provider
from tests.api.omnicult_support import add_member, client_for, draft, put_claims, seeded, source  # noqa: F401
from tests.api.proof_support import API, add_run, campaign_with_regions, step, tamil_nadu_claims
from tests.conftest import BOB

ORDER = [
    "campaign_brief", "target_regions", "region_claims", "evidence_meter", "conflicts", "creative_versions",
    "xray_findings", "risk_findings", "transcreation", "audience_results", "readiness", "approvals", "live_performance",
    "limitations", "run_history",
]
STUBS = ["creative_versions", "xray_findings", "risk_findings", "transcreation", "audience_results", "readiness",
         "approvals", "live_performance"]


async def make_report(client: httpx.AsyncClient, campaign_id: str, **body: Any) -> dict[str, Any]:
    response = await client.post(f"{API}/campaigns/{campaign_id}/proof-reports", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def section(report: dict[str, Any], section_id: str) -> dict[str, Any]:
    return next(s for s in report["sections"] if s["id"] == section_id)


async def test_the_registry_covers_every_section_and_unwired_ones_report_missing(seeded: Any, client: httpx.AsyncClient) -> None:
    assert set(REGISTRY) == set(SECTION_MODELS)
    listed = (await client.get(f"{API}/proof-report-sections")).json()
    assert [s["id"] for s in listed] == ORDER
    assert {s["id"] for s in listed if not s["wired"]} == set(STUBS)
    setup = await campaign_with_regions(client)
    await tamil_nadu_claims(setup["workspace_id"])
    report = await make_report(client, setup["campaign"]["id"])
    assert [s["id"] for s in report["sections"]] == ORDER and report["assembly"]["section_ids"] == ORDER
    for stub in STUBS:  # a placeholder says so; it never looks like an empty, complete section
        found = section(report, stub)
        assert (found["status"], found["missing_reason"], found["content"], found["kind_labels"]) == ("missing", NOT_IN_BUILD, None, [])
    assert [m["id"] for m in report["missing_sections"]] == STUBS and report["status"] == "partial"
    for wired in set(ORDER) - set(STUBS):
        found = section(report, wired)
        assert found["status"] == "available" and found["missing_reason"] is None and found["kind_labels"], wired


async def test_every_available_section_labels_its_content_kinds(seeded: Any, client: httpx.AsyncClient) -> None:
    setup = await campaign_with_regions(client)
    await tamil_nadu_claims(setup["workspace_id"])
    report = await make_report(client, setup["campaign"]["id"])
    kinds = {label["kind"] for s in report["sections"] for label in s["kind_labels"]}
    assert kinds <= {"observed", "calculated", "synthetic", "interpretation", "unverified"}
    claims = section(report, "region_claims")
    assert {label["kind"] for label in claims["kind_labels"]} == {"observed", "calculated", "interpretation"}
    assert claims["content"]["kind_counts"] == {"observed": 4, "calculated": 1, "interpretation": 1}
    assert {label["kind"] for label in section(report, "evidence_meter")["kind_labels"]} == {"calculated"}
    assert {label["kind"] for label in section(report, "run_history")["kind_labels"]} == {"observed", "calculated"}
    assert [k["kind"] for k in report["kind_legend"]] == ["observed", "calculated", "synthetic", "interpretation", "unverified"]
    assert "not legal clearance" in report["legal_notice"].lower() and "legal advice" in report["legal_notice"]
    assert "not legal clearance" in " ".join(section(report, "limitations")["content"]["items"]).lower()


async def test_claims_are_grouped_by_category_with_their_five_tags_and_regions_come_from_the_campaign(
    seeded: Any, client: httpx.AsyncClient
) -> None:
    setup = await campaign_with_regions(client)
    await tamil_nadu_claims(setup["workspace_id"])
    report = await make_report(client, setup["campaign"]["id"])
    assert report["target_region_codes"] == ["IN-TN", "IN-KL"]
    assert section(report, "target_regions")["content"]["source"] == "campaign"
    blocks = {b["region_code"]: b for b in section(report, "region_claims")["content"]["regions"]}
    tn = blocks["IN-TN"]
    assert len(tn["categories"]) == 14  # every category, so a gap is visible
    festival = next(c for c in tn["categories"] if c["category"] == "festival")["claims"][0]
    assert festival["value_text"] == "Pongal is the main harvest festival."
    assert festival["kind"] == "observed" and festival["confidence"] == "moderate" and festival["scope"]["region_code"] == "IN-TN"
    assert len(festival["sources"]) == 2 and festival["retrieved_at"]
    assert next(c for c in tn["categories"] if c["category"] == "food")["claims"] == []
    kolam = next(c for c in tn["categories"] if c["category"] == "symbol")["claims"][0]
    assert kolam["kind"] == "interpretation" and kolam["confidence"] == "low"
    assert blocks["IN-KL"]["claim_count"] == 1
    assert section(report, "evidence_meter")["content"]["meters"][0]["strength"] == "weak"
    assert any("weak" in item for item in section(report, "limitations")["content"]["items"])
    assert set(map(UUID, report["referenced_claim_ids"])) >= {UUID(festival["id"]), UUID(kolam["id"])}


async def test_open_and_resolved_conflicts_are_reported_with_decisions(seeded: Any, client: httpx.AsyncClient) -> None:
    setup = await campaign_with_regions(client)
    ws = setup["workspace_id"]
    await tamil_nadu_claims(ws)
    first = await make_report(client, setup["campaign"]["id"])
    content = section(first, "conflicts")["content"]
    assert (len(content["open"]), len(content["resolved"])) == (1, 0)
    conflict = content["open"][0]
    assert conflict["region_code"] == "IN-TN" and "language_share" in conflict["reason"]
    assert {conflict["side_a"]["kind"], conflict["side_b"]["kind"]} == {"observed"}
    assert any("1 conflict is unresolved" in item for item in section(first, "limitations")["content"]["items"])

    decided = await client.post(f"{API}/workspaces/{ws}/conflicts/{conflict['id']}/resolve", json={"decision": "accept", "note": "checked"})
    assert decided.status_code == 200, decided.text
    second = await make_report(client, setup["campaign"]["id"])
    content = section(second, "conflicts")["content"]
    assert (len(content["open"]), len(content["resolved"])) == (0, 1)
    assert [d["decision"] for d in content["resolved"][0]["decisions"]] == ["accept"]
    assert {label["kind"] for label in section(second, "conflicts")["kind_labels"]} == {"calculated", "observed"}
    assert conflict["id"] in second["referenced_conflict_ids"]


async def test_run_history_in_the_report_carries_model_prompt_tokens_and_estimated_cost(seeded: Any, client: httpx.AsyncClient) -> None:
    setup = await campaign_with_regions(client)
    await tamil_nadu_claims(setup["workspace_id"])
    pid, cid = setup["project"]["id"], setup["campaign"]["id"]
    await add_run(pid, cid, steps=[step(cost=0.002), step("brief", cost=0.003, tokens_in=10, tokens_out=5)])
    await add_run(pid, cid, status="failed", steps=[step(cost=None)], error={"code": "PROVIDER_ERROR", "message": "Provider failed.", "stage": "interpret", "retryable": True})
    report = await make_report(client, cid)
    content = section(report, "run_history")["content"]
    assert content["totals"]["runs"] == 2 and content["totals"]["cost_is_estimate"] is True
    assert content["totals"]["estimated_cost_usd"] == pytest.approx(0.005) and content["totals"]["runs_without_cost"] == 1
    done = next(r for r in content["runs"] if r["status"] == "completed")
    assert done["models"] == ["gemini-3.5-flash-lite"] and done["prompt_versions"] == ["atlas.v1"] and done["input_tokens"] == 110
    assert any("lower bound" in item for item in section(report, "limitations")["content"]["items"])


async def test_a_campaign_without_regions_gets_missing_region_sections_not_empty_ones(seeded: Any, client: httpx.AsyncClient) -> None:
    from tests.api.test_crud import make_campaign, make_project

    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    report = await make_report(client, campaign["id"])
    for name in ("target_regions", "region_claims", "evidence_meter", "conflicts"):
        found = section(report, name)
        assert found["status"] == "missing" and "target regions" in found["missing_reason"], name
    assert section(report, "campaign_brief")["status"] == "available" and report["target_region_codes"] == []
    asked = await make_report(client, campaign["id"], region_codes=["IN-TN", "IN-XX"])  # a request supplies regions
    assert asked["target_region_codes"] == ["IN-TN"]
    assert section(asked, "target_regions")["content"]["source"] == "request"
    assert section(asked, "target_regions")["content"]["unknown_codes"] == ["IN-XX"]
    assert section(asked, "region_claims")["status"] == "missing" and "No claims" in section(asked, "region_claims")["missing_reason"]
    assert (await client.post(f"{API}/campaigns/{campaign['id']}/proof-reports", json={"region_codes": ["tamil"]})).status_code == 422


async def test_a_failing_or_misbehaving_provider_makes_its_section_missing_and_a_registered_one_plugs_in(
    seeded: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(proof_sections, "REGISTRY", dict(REGISTRY))

    @provider("xray_findings")
    async def broken(ctx: SectionContext) -> Provided | Missing:
        raise RuntimeError("boom")

    @provider("readiness")
    async def wrong_type(ctx: SectionContext) -> Provided | Missing:
        return Provided(proof_sections.TargetRegionsContent(source="campaign", regions=[], unknown_codes=[]),
                        [proof_sections.KindLabel(kind="calculated", applies_to="x")])

    @provider("approvals")
    async def wired(ctx: SectionContext) -> Provided | Missing:
        from app.schemas.proof import ApprovalItem, ApprovalsContent

        item = ApprovalItem(id="a1", version_id=None, approver_user_id=None, role="reviewer", decision="approved", note="ok", decided_at=utcnow())
        return Provided(ApprovalsContent(approvals=[item]), [proof_sections.KindLabel(kind="observed", applies_to="Recorded approvals.")])

    setup = await campaign_with_regions(client)
    report = await make_report(client, setup["campaign"]["id"])
    assert "RuntimeError" in section(report, "xray_findings")["missing_reason"] and section(report, "xray_findings")["content"] is None
    assert section(report, "readiness")["status"] == "missing"  # content of the wrong type is refused
    approvals = section(report, "approvals")
    assert approvals["status"] == "available" and approvals["content"]["approvals"][0]["kind"] == "observed"
    assert "approvals" not in [m["id"] for m in report["missing_sections"]]
    with pytest.raises(ValueError):
        Provided(proof_sections.EvidenceMeterContent(meters=[]), [])  # a provider must say what kinds it holds


async def test_snapshots_are_versioned_and_equal_inputs_give_an_equal_hash(seeded: Any, client: httpx.AsyncClient) -> None:
    setup = await campaign_with_regions(client)
    await tamil_nadu_claims(setup["workspace_id"])
    cid = setup["campaign"]["id"]
    one, two = await make_report(client, cid, title="Launch proof"), await make_report(client, cid)
    assert (one["version_number"], two["version_number"]) == (1, 2) and one["title"] == "Launch proof"
    assert two["title"] == "Proof Report: Autumn" and one["content_sha256"] == two["content_sha256"] and len(one["content_sha256"]) == 64
    assert one["campaign_version_id"] == setup["campaign"]["current_version"]["id"]
    assert one["assembly"] == {"method": "deterministic", "model_called": False, "registry_version": "proof-sections-v1", "section_ids": ORDER}
    assert (await client.get(f"{API}/proof-reports/{one['id']}")).json() == one  # a snapshot is stored, not recomputed
    await put_claims(setup["workspace_id"], [draft("Thai Pusam", sources=[source("wikimedia")])])
    three = await make_report(client, cid)
    assert three["content_sha256"] != one["content_sha256"] and three["version_number"] == 3
    assert (await client.get(f"{API}/proof-reports/{one['id']}")).json()["content_sha256"] == one["content_sha256"]  # v1 untouched
    listed = (await client.get(f"{API}/campaigns/{cid}/proof-reports")).json()
    assert [r["version_number"] for r in listed["items"]] == [3, 2, 1] and "sections" not in listed["items"][0]
    async with read_session() as s:
        audit = (await s.execute(select(m.AuditLog).where(m.AuditLog.action == "proof_report.create"))).scalars().all()
    assert len(audit) == 3


async def test_exports_json_markdown_and_pdf_keep_labels_and_the_legal_notice(seeded: Any, client: httpx.AsyncClient) -> None:
    setup = await campaign_with_regions(client)
    await tamil_nadu_claims(setup["workspace_id"])
    report = await make_report(client, setup["campaign"]["id"], title="Launch proof")
    base = f"{API}/proof-reports/{report['id']}/export"
    as_json = await client.get(base, params={"format": "json"})
    assert as_json.headers["content-disposition"] == 'attachment; filename="omnicult-launch-proof-v1.json"'
    assert json.loads(as_json.content) == report
    markdown = await client.get(base, params={"format": "markdown"})
    text = markdown.text
    assert markdown.headers["content-type"].startswith("text/markdown") and text.startswith("# Launch proof")
    for expected in ("not legal clearance", "## How to read this report", "Regional evidence: claims by category", "Pongal is the main harvest festival.",
                     "Not included: not available in this build.", "## Run and model metadata", "observed:", "calculated:", "## Missing sections"):
        assert expected.lower() in text.lower(), expected
    pdf = await client.get(base)  # pdf is the default
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF-")
    assert pdf.headers["content-disposition"].endswith('-v1.pdf"') and b"Launch proof" in pdf.content and len(pdf.content) > 2000
    assert (await client.get(base, params={"format": "docx"})).status_code == 422


async def test_a_stored_export_has_a_short_lived_link_that_needs_no_bearer_token(
    seeded: Any, client: httpx.AsyncClient, client_for: Any
) -> None:
    setup = await campaign_with_regions(client)
    await tamil_nadu_claims(setup["workspace_id"])
    report = await make_report(client, setup["campaign"]["id"])
    made = await client.post(f"{API}/proof-reports/{report['id']}/exports", json={"format": "pdf"})
    assert made.status_code == 201, made.text
    export = made.json()
    assert export["content_type"] == "application/pdf" and export["byte_size"] > 2000 and export["notices"] == []
    expires = datetime.fromisoformat(export["expires_at"].replace("Z", "+00:00"))
    assert timedelta(seconds=240) < expires - utcnow() <= timedelta(seconds=300)
    anonymous = client_for({})  # the link alone grants the download
    got = await anonymous.get(export["download_url"])
    assert got.status_code == 200 and got.content.startswith(b"%PDF-") and len(got.content) == export["byte_size"]
    assert got.headers["content-disposition"] == f'attachment; filename="{export["filename"]}"' and got.headers["cache-control"] == "private, no-store"
    assert hashlib.sha256(got.content).hexdigest() == export["sha256"]
    path, token = export["download_url"].split("?token=")
    assert (await anonymous.get(path, params={"token": "x" * 43})).status_code == 404  # wrong token
    assert (await anonymous.get(path)).status_code == 422  # no token
    async with session() as s, s.begin():  # the token itself is never stored
        row = (await s.execute(select(m.ProofReportExport))).scalar_one()
        assert token not in (row.token_hash, row.storage_key) and row.token_hash != token
        row.expires_at = utcnow() - timedelta(seconds=1)
    assert (await anonymous.get(export["download_url"])).status_code == 404  # expired
    assert (await anonymous.get(f"{API}/proof-exports/{UUID(int=1)}/download", params={"token": token})).status_code == 404


async def test_export_bytes_go_through_the_blob_store_when_it_is_not_the_database(
    seeded: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("ASSET_STORAGE_BACKEND", "local")
    get_settings.cache_clear()
    monkeypatch.setattr(blobs, "LOCAL_ROOT", tmp_path / "blobs")
    setup = await campaign_with_regions(client)
    await tamil_nadu_claims(setup["workspace_id"])
    report = await make_report(client, setup["campaign"]["id"])
    export = (await client.post(f"{API}/proof-reports/{report['id']}/exports", json={"format": "markdown"})).json()
    async with read_session() as s:
        row = (await s.execute(select(m.ProofReportExport))).scalar_one()
    assert row.data is None and row.storage_key.startswith(f"proof/{setup['project']['id']}/{report['id']}/")
    assert (tmp_path / "blobs" / row.storage_key).read_bytes().startswith(b"# Proof Report")
    got = await client.get(export["download_url"])
    assert got.status_code == 200 and got.text.startswith("# Proof Report") and got.headers["content-type"].startswith("text/markdown")


async def test_indic_text_is_kept_in_json_and_markdown_and_transliterated_in_the_pdf_with_a_notice(
    seeded: Any, client: httpx.AsyncClient
) -> None:
    setup = await campaign_with_regions(client, ("IN-TN",))
    await put_claims(setup["workspace_id"], [draft("Pongal", sources=[source("wikimedia")], text="Pongal: பொங்கல் is the harvest festival.")])
    report = await make_report(client, setup["campaign"]["id"])
    assert "பொங்கல்" in (await client.get(f"{API}/proof-reports/{report['id']}/export", params={"format": "markdown"})).text
    made = (await client.post(f"{API}/proof-reports/{report['id']}/exports", json={"format": "pdf"})).json()
    assert len(made["notices"]) == 1 and "Tamil" in made["notices"][0] and "transliteration" in made["notices"][0]
    pdf = (await client.get(made["download_url"])).content
    assert "பொங்கல்".encode() not in pdf and pdf.startswith(b"%PDF-")


async def test_reports_and_exports_cannot_cross_workspaces_and_viewers_cannot_create(
    seeded: Any, client: httpx.AsyncClient, client_for: Any
) -> None:
    setup = await campaign_with_regions(client)
    await tamil_nadu_claims(setup["workspace_id"])
    cid = setup["campaign"]["id"]
    report = await make_report(client, cid)
    export = (await client.post(f"{API}/proof-reports/{report['id']}/exports", json={"format": "json"})).json()
    bob = client_for(BOB)
    assert (await bob.post(f"{API}/campaigns/{cid}/proof-reports", json={})).status_code == 404
    assert (await bob.get(f"{API}/campaigns/{cid}/proof-reports")).status_code == 404
    assert (await bob.get(f"{API}/proof-reports/{report['id']}")).status_code == 404
    assert (await bob.get(f"{API}/proof-reports/{report['id']}/export")).status_code == 404
    assert (await bob.post(f"{API}/proof-reports/{report['id']}/exports", json={"format": "json"})).status_code == 404
    assert (await bob.get(f"{API}/workspaces/{setup['workspace_id']}/claims/{report['referenced_claim_ids'][0]}")).status_code == 404
    await add_member(setup["workspace_id"], "bob", "viewer")
    assert (await bob.get(f"{API}/proof-reports/{report['id']}")).json() == report  # a member can read
    assert (await bob.post(f"{API}/proof-reports/{report['id']}/exports", json={"format": "json"})).status_code == 201
    assert (await bob.post(f"{API}/campaigns/{cid}/proof-reports", json={})).status_code == 403  # but not create
    claim = await bob.get(f"{API}/workspaces/{setup['workspace_id']}/claims/{report['referenced_claim_ids'][0]}")
    assert claim.status_code == 200 and claim.json()["sources"] is not None
    assert (await client.get(export["download_url"])).status_code == 200


async def test_assemble_runs_deferred_sections_last_and_reads_earlier_results(seeded: Any, client: httpx.AsyncClient) -> None:
    setup = await campaign_with_regions(client)
    ctx = await proof_sections.build_context(dev_user_id("alice"), UUID(setup["campaign"]["id"]), None)
    sections = await assemble(ctx)
    assert [s.id for s in sections] == ORDER
    assert list(ctx.results)[-1] == "limitations"  # ran after every other section, so it could read them
