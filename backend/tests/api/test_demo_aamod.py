"""The Aamod demo journey: POST /projects/demo seeds the fictional brand across every workspace, deterministically, with no
provider and no network, labelled as demonstration data, once per user (a repeat returns the same project).

The seed runs the real services and workflows with the labelled fixture model, so these tests read the result through the same
API and tables the UI reads. One test seeds once and checks the whole story (a seed is the slow part); the cheap tests check the
fixture phrasebook against the real code checks and the responders' honesty.
"""

import asyncio
import socket
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select

from app.analytics.risk_rules import RULES_VERSION
from app.core.auth import dev_user_id
from app.core.config import get_settings
from app.db import models as m
from app.db.session import read_session
from app.fixtures import demo_aamod as fx
from app.fixtures.audience_llm import AUDIENCE_RESPONDERS
from app.fixtures.demo_llm import RESPONDERS
from app.services import claims as claim_service
from app.services import studio_context as studio_ctx
from app.services.demo_journey import PROJECT_NAME, glossary_rows, scene_uuid
from app.studio.checks import min_share_for, script_check, term_checks, term_problems
from tests.api.omnicult_support import draft, put_claims, workspace_of
from tests.conftest import BOB

API = "/api/v1"
CLAIM = fx.CLAIM_QUOTE
TAGLINE = fx.TAGLINE


# --- cheap checks (no database) ---------------------------------------------------------------------------------------


def _entries() -> list[dict[str, Any]]:
    return [{"prohibited_alternatives": [], "approved_spelling": None, "preferred_translation": None, "script": None, **r}
            for r in glossary_rows(fx.load("brand_glossary.json"))]


def test_every_phrasebook_line_passes_the_real_script_and_glossary_checks():
    """The Tamil, Malayalam and Bengali lines are fixtures: they must clear the same code checks a live line must clear."""
    original = fx.load("creative_mh_original.json")
    texts = {e["value"] for c in original["creatives"] for e in c["elements"] if isinstance(e["value"], str)}
    assert set(fx.PHRASEBOOK) <= texts, "every phrasebook source is a line of the original creative"
    protected = ["Aamod", "Aamod Festive Tin", TAGLINE]
    prohibited = ["No. 1", "number one", "world's best"]
    for source, row in fx.PHRASEBOOK.items():
        for plan in fx.ADAPTATIONS:
            line = row[plan.language]
            checks = term_checks(source, line.copy, line.back, _entries(), language=plan.language, protected=protected, prohibited=prohibited)
            assert term_problems(checks) == [], (source, plan.language, checks)
            script = script_check(line.copy, plan.script, preserved=checks["preserved_terms"], min_share=min_share_for(plan.tone["code_mixing"]))
            assert script["ok"], (source, plan.language, script["message"])
            assert len(line.why) <= 500 and line.back


def test_product_names_use_the_glossary_spelling_and_the_back_translation_keeps_the_brand_words():
    entries = _entries()
    for plan, spelling in zip(fx.ADAPTATIONS, ("ஆமோத் ஃபெஸ்டிவ் டின்", "ആമോദ് ഫെസ്റ്റിവ് ടിൻ", "আমোদ ফেস্টিভ টিন")):
        line = fx.PHRASEBOOK["Aamod Festive Tin"][plan.language]
        assert line.copy == spelling and line.back == "Aamod Festive Tin"
        assert any(e["term"] == "Aamod Festive Tin" and e["language"] == plan.language and e["approved_spelling"] == spelling for e in entries)


def test_the_responders_answer_only_for_the_aamod_copy():
    unknown = {"lines": {"L1": {"text": "Happy Diwali from somewhere else", "kind": "headline"}}, "language": "ta", "claims": [], "tone": {"formality": 50}}
    assert fx.transcreate_lines(unknown) is None
    value = {"element": {"value": "an unrelated line"}, "region": "Tamil Nadu (IN-TN)", "claims": [], "count": 3}
    assert fx.tweak_chips(value) is None
    assert fx.risk_findings({"elements": [{"handle": "E1", "text": "Shop now"}]}) is None
    assert fx.xray_scenes({"creative": {"kind": "video"}, "transcript": [{"id": "t1", "start_ms": 0, "end_ms": 900, "text": "hello"}]}) is None
    assert fx.xray_scenes({"creative": {"kind": "image"}, "transcript": []}) is None
    for prompt in ("xray-scenes-v1", "transcreate-lines-v1", "tweak-chips-v1", "quick-read-v1", "risk-check-v1"):
        assert prompt in RESPONDERS or prompt in AUDIENCE_RESPONDERS


def test_the_xray_responder_proposes_only_observations_that_rest_on_a_transcript_segment():
    from app.agents.xray import XRayScenesOut

    transcript = [{"id": f"t{n}", "start_ms": t["start_ms"], "end_ms": t["end_ms"], "text": t["text"]}
                  for n, t in enumerate(fx.load("creative_mh_original.json")["creatives"][0]["transcript"], 1)]
    answer = fx.xray_scenes({"creative": {"kind": "video"}, "transcript": transcript})
    scenes = XRayScenesOut.model_validate(answer).scenes
    assert len(scenes) == 5 and scenes[0].start_ms == 0 and scenes[-1].end_ms == 29400
    cited = {e for s in scenes for o in s.observations for e in o.evidence}
    assert cited <= {t["id"] for t in transcript} and cited, "no frame is cited: a demo project has no vision model"
    assert any("Bhau Beej" in o.text for s in scenes for o in s.observations)
    assert all(s.on_screen_text == [] and s.claims == [] for s in scenes), "visual and on-screen fields would be discarded"


# --- the whole journey --------------------------------------------------------------------------------------------------


@contextmanager
def no_network() -> Iterator[None]:
    """Any socket connection other than loopback fails the test: the seed must not reach a provider or any host."""
    real = socket.socket.connect

    def guard(self: socket.socket, address: Any) -> None:
        if not (isinstance(address, tuple) and str(address[0]) in ("127.0.0.1", "::1", "localhost")):
            raise AssertionError(f"the demo seed used the network: {address!r}")
        return real(self, address)

    socket.socket.connect = guard  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = real  # type: ignore[method-assign]


@pytest.fixture
async def aamod(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    """The shared client with the Aamod seed on (the suite pins the legacy seed for the pre-Omnicult tests)."""
    monkeypatch.setenv("DEMO_SEED", "aamod")
    get_settings.cache_clear()
    return client


async def rows(model: Any, *where: Any) -> list[Any]:
    async with read_session() as s:
        return list((await s.execute(select(model).where(*where))).scalars())


async def get(client: httpx.AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(f"{API}{path}", params=params)
    assert response.status_code == 200, (path, response.text)
    return response.json()


async def test_try_the_demo_seeds_the_whole_aamod_journey(aamod: httpx.AsyncClient) -> None:
    client = aamod
    started = time.perf_counter()
    with no_network():
        created = await client.post(f"{API}/projects/demo")
    seconds = time.perf_counter() - started
    assert created.status_code == 201, created.text
    project = created.json()
    pid, user = project["id"], dev_user_id("alice")
    print(f"\nAamod seed took {seconds:.1f} s (first seed in an empty database, includes the shared claims)")

    # -- brand, brief, campaign: labelled, fictional, demo ------------------------------------------------------------
    assert project["mode"] == "demo" and project["name"] == PROJECT_NAME and "Fictional brand" in project["description"]
    brand = project["brand"]
    assert brand["name"] == "Aamod" and TAGLINE in brand["protected_terms"] and "Aamod Festive Tin" in brand["protected_terms"]
    assert any("superiority" in c.lower() for c in brand["constraints"]), "the claims policy is in the brand constraints"
    campaigns = (await get(client, f"/projects/{pid}/campaigns"))["items"]
    assert len(campaigns) == 1
    cid = campaigns[0]["id"]
    assert campaigns[0]["current_version"]["version_number"] == 1 and len(campaigns[0]["versions"]) == 1, "scratch content versions are gone"
    assert campaigns[0]["current_version"]["content"]["headline"] == "दिवाळी म्हणजे फराळ!"

    # -- idempotent per user, separate per user -----------------------------------------------------------------------
    again = await client.post(f"{API}/projects/demo")
    assert again.status_code == 201 and again.json()["id"] == pid
    assert [p["id"] for p in (await get(client, "/projects"))["items"]] == [pid]
    assert (await client.get(f"{API}/projects", headers=BOB)).json()["items"] == []

    # -- Brand Glossary -----------------------------------------------------------------------------------------------
    glossary = (await get(client, f"/campaigns/{cid}/glossary", limit=100))["items"]
    spellings = {(g["term"], g["language"]): g["approved_spelling"] for g in glossary}
    assert spellings[("Aamod Festive Tin", "ta")] == "ஆமோத் ஃபெஸ்டிவ் டின்" and spellings[("Aamod", "bn")] == "আমোদ"
    assert next(g for g in glossary if g["term"] == "Aamod Festive Tin" and g["language"] == "*")["never_translate"] is True

    # -- stored assets and Creative X-Ray -----------------------------------------------------------------------------
    assets = await rows(m.Asset, m.Asset.project_id == UUID(pid))
    video = next(a for a in assets if a.kind == "video")
    assert video.duration_ms == 29400 and video.rights_confirmed and video.processing_status == "ready"
    assert {a.derived_role for a in assets if a.parent_asset_id == video.id} == {"keyframe", "thumbnail"}
    assert sum(a.derived_role == "keyframe" for a in assets) == 5 and sum(a.kind == "image" and a.parent_asset_id is None for a in assets) == 6
    creatives = (await get(client, f"/campaigns/{cid}/creatives"))["items"]
    assert {c["kind"]: (c["status"], c["scene_count"], c["mode"]) for c in creatives} == {"video": ("completed", 5, "demo"), "image": ("completed", 1, "demo")}
    film = next(c for c in creatives if c["kind"] == "video")
    detail = await get(client, f"/creatives/{film['id']}")
    assert detail["analysis"]["transcribe"]["provider"] == "fixture" and detail["analysis"]["vision"]["provider"] == "fixture"
    assert len(detail["analysis"]["transcript"]) == 6 and len(detail["analysis"]["frames"]) == 5
    scenes = (await get(client, f"/creatives/{film['id']}/scenes"))["items"]
    end_card = scenes[4]
    assert end_card["id"] == str(scene_uuid(UUID(pid), "mh-s5")) and end_card["start_ms"] == 19912 and end_card["end_ms"] == 29400
    assert [c["text"] for c in end_card["claims"]] == [CLAIM] and end_card["claims"][0]["source"] == "on_screen_text"
    assert any(CLAIM in t["text"] for t in end_card["on_screen_text"]) and end_card["keyframe_url"]
    assert all(s["cultural_observations"] and s["cultural_interpretations"] for s in scenes)
    assert all(i["limitations"] for s in scenes for i in s["cultural_interpretations"]), "interpretations are never presented as facts"
    assert any("faral" in o["text"] for o in scenes[0]["cultural_observations"]) and any("Bhau Beej" in o["text"] for o in scenes[3]["cultural_observations"])
    kv = next(c for c in creatives if c["kind"] == "image")
    kv_scene = (await get(client, f"/creatives/{kv['id']}/scenes"))["items"][0]
    assert [c["text"] for c in kv_scene["claims"]] == [CLAIM]

    # -- region claims: shared demo claims, never live ones; the two genuine conflicts -------------------------------------
    workspace = await workspace_of("alice")
    claims = await rows(m.Claim)
    assert len(claims) > 150 and {c.mode for c in claims} == {"demo"} and all(c.workspace_id is None for c in claims)
    assert {c.region_id for c in claims} >= {r.id for r in await rows(m.Region, m.Region.code.in_(fx_regions()))}
    conflicts = await get(client, f"/workspaces/{workspace}/conflicts", mode="demo", status="open")
    reasons = [c["reason"] for c in conflicts["items"]]
    assert len(reasons) == 2, reasons
    assert any("language_share" in r and "IN-WB" in r for r in reasons) and any("dahi_handi" in r for r in reasons)
    tn = await get(client, f"/workspaces/{workspace}/regions/IN-TN/profile", mode="demo")
    assert tn["meter"]["claims"] > 20 and tn["meter"]["strength"] in ("partial", "solid")
    await put_claims(workspace, [draft("LIVE-ONLY", attribute="live_only", region="IN-TN", kind="unverified", text="LIVE-ONLY statement")], mode="live")
    async with read_session() as s:
        demo_project = await s.get(m.Project, UUID(pid))
        region = await studio_ctx.region_named(s, "IN-TN")
        offered = await studio_ctx.region_claims(s, demo_project, region)
        shown = (await s.execute(select(m.Claim.value_text).where(m.Claim.mode == "demo"))).scalars().all()
    assert offered and not any("LIVE-ONLY" in c["statement"] for c in offered) and "LIVE-ONLY statement" not in shown, "a demo project never reads live claims"

    # -- the version tree: v1 plus three adaptations, locks, back-translations, check results, chips ---------------------------
    nodes = (await get(client, f"/campaigns/{cid}/versions", limit=100))["items"]
    assert len(nodes) == 11 and [n["parent_id"] for n in nodes].count(None) == 1
    root = next(n for n in nodes if n["parent_id"] is None)
    assert root["region_code"] == "IN-MH" and root["language"] == "mr" and root["label"].startswith("Original")
    assert {n["region_code"] for n in nodes} == set(fx_regions())
    locks = (await get(client, f"/campaigns/{cid}/locks", limit=100))["items"]
    locked = {lock["element_id"] for lock in locks}
    assert len(locked) == 11 and {"mh-vid-tagline", "mh-kv-tagline", "mh-vid-logo", "mh-vid-packshot", "mh-vid-s3-product"} <= locked
    root_elements = {e["id"]: e for e in (await get(client, f"/campaigns/{cid}/versions/{root['id']}"))["elements"]}
    assert {i for i, e in root_elements.items() if e["locked"]} == locked
    assert root_elements["mh-vid-small-print"]["value"].endswith("फराळ टिन.") and CLAIM in root_elements["mh-vid-small-print"]["value"]
    assert root_elements["mh-vid-packshot"]["scene_id"] == str(scene_uuid(UUID(pid), "mh-s5")), "elements point at the stored X-Ray scenes"
    operations = (await get(client, f"/campaigns/{cid}/operations", limit=100))["items"]
    assert len(operations) == 10 and all(o["status"] == "applied" for o in operations)
    transcreations = [o for o in operations if o["kind"] == "transcreate"]
    assert sorted(o["params"]["language"] for o in transcreations) == ["bn", "ml", "ta"]
    for operation in transcreations:
        lines = operation["params"]["lines"]
        assert len(lines) == 18 and all(x["passed"] and x["back_translation"] and x["script_check"]["ok"] for x in lines)
        assert all(x["term_checks"]["protected_preserved"] for x in lines)
        assert any(x["preserved_terms"] for x in lines), "the Brand Glossary spelling was applied and checked in code"
    finals = {n["region_code"]: n for n in nodes if n["label"].endswith("unsourced claim replaced")}
    assert set(finals) == {"IN-TN", "IN-KL", "IN-WB"} and all(n["actor"] == "user" for n in finals.values())
    for code, node in finals.items():
        elements = {e["id"]: e for e in (await get(client, f"/campaigns/{cid}/versions/{node['id']}"))["elements"]}
        for element_id in locked:  # locked elements are unchanged in every adaptation
            assert elements[element_id]["value"] == root_elements[element_id]["value"], (code, element_id)
        assert CLAIM not in elements["mh-vid-small-print"]["value"] and CLAIM not in elements["mh-kv-small-print"]["value"]
        assert elements["mh-vid-s1-headline"]["language"] == node["language"] and elements["mh-vid-s1-headline"]["value"] != root_elements["mh-vid-s1-headline"]["value"]
    assert "தீபாவளிக்கு" in {e["id"]: e for e in (await get(client, f"/campaigns/{cid}/versions/{finals['IN-TN']['id']}"))["elements"]}["mh-vid-cta-hook"]["value"]
    seeded_chips = (await get(client, f"/campaigns/{cid}/chips", limit=100))["items"]
    assert len(seeded_chips) == 4 and all(c["status"] == "applied" and c["claim_ids"] and c["provider"] == "fixture" for c in seeded_chips)
    diff = await get(client, f"/campaigns/{cid}/versions/{root['id']}/diff/{finals['IN-TN']['id']}")
    assert diff["changed"] and set(diff["preserved"]) >= locked

    # -- Audience Lab: the planted risk is found, anchored and cited ---------------------------------------------------------------
    runs = await rows(m.AudienceRun, m.AudienceRun.project_id == UUID(pid))
    assert len(runs) == 8 and {r.mode for r in runs} == {"demo"} and {r.status for r in runs} == {"completed"}
    assert all(r.version_ref and r.content_version_id is None and r.usage["model_stages"] == 0 for r in runs)
    risk_runs = {r.region_codes[0]: r for r in runs if r.kind == "risk_check"}
    original_risk = await get(client, f"/campaigns/{cid}/risk-checks/{risk_runs['IN-MH'].id}")
    assert original_risk["rules_version"] == RULES_VERSION and original_risk["mode"] == "demo" and original_risk["human_review_required"] is True
    found = {f["element_id"]: f for f in original_risk["findings"] if f["category"] == "comparative_claim"}
    end_card_finding, kv_finding = found["mh-vid-small-print"], found["mh-kv-small-print"]
    assert end_card_finding["quote"] == CLAIM and end_card_finding["severity"] == "high" and end_card_finding["blocks_go"] is True
    assert end_card_finding["anchor"]["scene_id"] == end_card["id"] and end_card_finding["anchor"]["start_ms"] == 19912
    assert end_card_finding["anchor"]["bbox"] == [0.2528, 0.7943, 0.4935, 0.0156]
    assert end_card_finding["verification"] == "quote_verified" and end_card_finding["source"] == "model_assessment"
    assert {a["id"] for a in end_card_finding["ad_codes"]} >= {"asci-1-1"} and all(a["clause"] for a in end_card_finding["ad_codes"])
    assert any(r["rule"] == "R2_ad_code" for r in end_card_finding["severity_rules"])
    assert kv_finding["quote"] == CLAIM and kv_finding["anchor"]["scene_id"] == kv_scene["id"] and kv_finding["anchor"]["bbox"]
    assert {f["category"] for f in original_risk["findings"]} == {"comparative_claim", "disclaimer_issue"}
    assert original_risk["counts"]["blocking_go"] == 1
    for code in ("IN-TN", "IN-KL", "IN-WB"):
        adapted = await get(client, f"/campaigns/{cid}/risk-checks/{risk_runs[code].id}")
        assert all(f["category"] != "comparative_claim" for f in adapted["findings"]), code
        assert adapted["counts"]["blocking_go"] == 0
    quick = {r.region_codes[0]: r for r in runs if r.kind == "quick_read"}
    tn_quick = await get(client, f"/campaigns/{cid}/quick-reads/{quick['IN-TN'].id}")
    assert tn_quick["disclosure"] and len(tn_quick["participants"]) == 12 and all(p["is_synthetic"] for p in tn_quick["participants"])
    assert tn_quick["version_ref"] == finals["IN-TN"]["id"] and {p["state_code"] for p in tn_quick["participants"]} == {"IN-TN"}

    # -- Readiness Board: the story is computed by the rules ------------------------------------------------------------------
    board = (await get(client, f"/campaigns/{cid}/readiness"))["regions"]
    verdicts = {r["region_code"]: r["versions"][0]["verdict"] for r in board}
    assert set(verdicts) == set(fx_regions()) and all(v["mode"] == "demo" for v in verdicts.values())
    assert verdicts["IN-MH"]["verdict"] == "fix" and verdicts["IN-MH"]["version_id"] == root["id"]
    assert "FX1_blocking_finding_unresolved" in verdicts["IN-MH"]["rules_applied"] and "F1" in verdicts["IN-MH"]["main_reason"]
    assert verdicts["IN-MH"]["risk"]["blocking"] == 1
    assert verdicts["IN-TN"]["verdict"] == "go" and verdicts["IN-TN"]["version_id"] == finals["IN-TN"]["id"]
    assert verdicts["IN-TN"]["rules_applied"] == ["G0_no_blocking_rule"] and verdicts["IN-TN"]["confidence_limitations"]
    assert verdicts["IN-KL"]["verdict"] == "fix" and "FX6_message_partly_understood" in verdicts["IN-KL"]["rules_applied"]
    assert verdicts["IN-WB"]["verdict"] in ("go", "fix")
    assert all(v["main_reason"] and v["next_action"] and v["scoring_version"] == "mvp-2" for v in verdicts.values())
    assert all(v["provenance"]["model_id"] == "demo-fixture" and "demo-fixture" in v["provenance"]["evidence_snapshot"] for v in verdicts.values())

    # -- Live Pulse sample, Proof Report ----------------------------------------------------------------------------------------
    sample = await get(client, f"/campaigns/{cid}/pulse/sample-dataset")
    assert sample["loaded"] and sample["is_sample"] and sample["source_kind"] == "sample" and sample["row_count"] > 1000
    reports = (await get(client, f"/campaigns/{cid}/proof-reports"))["items"]
    assert len(reports) == 1 and reports[0]["mode"] == "demo" and reports[0]["campaign_version_id"] == campaigns[0]["current_version"]["id"]
    report = await get(client, f"/proof-reports/{reports[0]['id']}")
    assert report["schema_version"] == "proof-report-v2" and report["sections"] and report["legal_notice"]

    # -- everything seeded is labelled demo --------------------------------------------------------------------------------------
    for model in (m.AgentRun, m.AudienceRun, m.ReadinessVerdict, m.ProofReport, m.Project):
        mine = [r for r in await rows(model) if getattr(r, "project_id", getattr(r, "id", None)) == UUID(pid)]
        assert mine and {r.mode for r in mine} == {"demo"}, model.__tablename__
    assert {r.mode for r in await rows(m.Claim, m.Claim.workspace_id.is_(None))} == {"demo"}, "the shared claims are demo fixtures"
    assert {r.source_kind for r in await rows(m.MetricSeries)} == {"sample"}
    for step in [s for r in await rows(m.AgentRun, m.AgentRun.project_id == UUID(pid)) for s in r.steps]:
        assert step["provider"] in ("fixture", "nativeproof"), step

    # -- a user who presses Run in the demo project gets labelled fixture output, not a provider error ----------------------------
    plan = {"version_id": root["id"], "region_code": "IN-TN", "language": "ta"}
    response = await client.post(f"{API}/campaigns/{cid}/transcreate", json=plan)  # every unlocked text line of the original
    assert response.status_code == 202, response.text
    for _ in range(300):
        run = (await get(client, f"/runs/{response.json()['run_id']}"))
        if run["status"] in ("completed", "partial", "failed"):
            break
        await asyncio.sleep(0.05)
    assert run["status"] in ("completed", "partial"), run
    chips = await client.post(f"{API}/campaigns/{cid}/chips/generate", json={
        "version_id": root["id"], "element_id": "mh-vid-s1-headline", "region_code": "IN-TN"})
    assert chips.status_code == 201 and chips.json()["chips"] == [], chips.text  # nothing evidence-backed to propose: an honest answer
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.AiUsageEvent)) == 0, "no model was called"


def fx_regions() -> tuple[str, ...]:
    return ("IN-MH", *(p.region for p in fx.ADAPTATIONS))
