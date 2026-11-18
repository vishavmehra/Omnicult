"""Try the demo: the fictional Aamod journey, seeded across every workspace from `app/fixtures/omnicult_demo`.

One call (POST /projects/demo) builds a demo-mode project for the caller that carries the whole 10-scene story with no
provider and no network: the brief and brand kit, the Brand Glossary, the stored Maharashtra film and key visual with their
Creative X-Ray reading (including the planted unsourced superiority claim), the version tree with Tamil Nadu, Kerala and
West Bengal adaptations (locks, back-translations, check results, Tweak Chips), the region claims with their two genuine
conflicts, a Quick Read and a Risk Check per version, the Readiness Board, the Live Pulse sample dataset and a Proof Report.

It calls the real services and the real workflows (transcreate, chips, Quick Read, Risk Check, readiness, proof) with the
labelled fixture model (`app.fixtures`), so the stored data is exactly what the UI reads. Only two things are written
directly: rows that no service creates (the glossary seed, assets and the X-Ray reading, content versions) and the shared
demo region claims, which are fixture claims with `mode = "demo"`: a demo project reads only demo claims, never live ones.

Idempotent per user: a user who already has the demo project gets it back. Seeding is serialised per user in this process;
a failed seed archives its partial project, so the next press of "Try the demo" starts clean.
"""

import asyncio
import hashlib
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import delete, select, update

from app.agents.xray import SceneOut
from app.core.config import get_settings
from app.core.idempotency import idempotency_key_var
from app.db import blobs
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.fixtures import demo_aamod as fx
from app.fixtures import demo_aamod_xray as fxray
from app.integrations.culture import RegionProfileBuilder, build_culture_service
from app.integrations.culture.fixture import FIXTURE_TIME
from app.media import sidecar as sidecar_text
from app.media.types import PreparedFrame
from app.reference.seed import seed_reference_data
from app.schemas import audience as aus
from app.schemas import launch as ls
from app.schemas import versions as vs
from app.schemas.assets import VisionStatus, VisualObservation
from app.schemas.campaigns import DEFAULT_EVALUATION_CRITERIA
from app.schemas.common import Anchor, StepTrace
from app.schemas.projects import Project
from app.schemas.proof import ProofReportCreate
from app.schemas.runs import RunProgress, RunResultRef
from app.schemas.xray import MediaProbe, TranscribeStatus, TranscriptSegment
from app.services import audience, chips, desk, lab_t3, launch, proof_reports, pulse, transcreate, versions, xray
from app.services import claims as claim_service
from app.services.audit import record_audit
from app.services.identity import ensure_personal_workspace

logger = logging.getLogger("omnicult.demo")

PROJECT_NAME = "Aamod Festive Tin, Diwali 2027"
DEMO_LABEL = "Fictional brand · demo workspace."
MARKET = {"country_code": "IN", "display_name": "India: Maharashtra, Tamil Nadu, Kerala, West Bengal"}
ORIGIN = "IN-MH"
REGIONS = (ORIGIN, *(p.region for p in fx.ADAPTATIONS))
FIXTURE_LABEL = "Demonstration fixture (fictional brand Aamod). Not a live result."
MODEL = "demo-fixture"
PRIMARY_LANGUAGE = {"IN-MH": "mr", "IN-TN": "ta", "IN-KL": "ml", "IN-WB": "bn"}
CAMPAIGN_WINDOW = (date(2027, 10, 4), date(2027, 11, 1))  # the brief's dates
_DATE = re.compile(r"(20\d\d-\d\d-\d\d)")
POLL_SECONDS = 0.02
WAIT_LIMIT_SECONDS = 120
TERMINAL = ("completed", "partial", "failed", "cancelled")
_locks: dict[tuple[int, UUID | str], asyncio.Lock] = {}


def _lock(key: UUID | str) -> asyncio.Lock:
    """A lock per (event loop, key): a lock made in one loop is never awaited from another (tests start a loop per test)."""
    return _locks.setdefault((id(asyncio.get_running_loop()), key), asyncio.Lock())


# --- entry point ---------------------------------------------------------------------------------------------------


async def seed_aamod_journey(user_id: UUID) -> Project:
    """The caller's Aamod demo project, created on first use. Returns the project in the shape of POST /projects/demo."""
    from app.services.projects import get_project_detail

    async with _lock(user_id):
        existing = await _existing(user_id)
        if existing is not None:
            return await get_project_detail(user_id, existing)
        started = time.perf_counter()
        project_id = uuid4()
        token = idempotency_key_var.set(None)  # the many runs below are not retries of the caller's request
        try:
            async with _timed("reference data and shared claims"):
                await prepare_shared_data()
            await _build(user_id, project_id)
        except BaseException:
            await _archive_partial(project_id)
            raise
        finally:
            idempotency_key_var.reset(token)
        logger.info("demo journey seeded in %.2f s", time.perf_counter() - started)
    return await get_project_detail(user_id, project_id)


async def _existing(user_id: UUID) -> UUID | None:
    async with read_session() as s:
        return await s.scalar(
            select(m.Project.id).where(m.Project.owner_id == user_id, m.Project.mode == "demo", m.Project.status == "active",
                                       m.Project.name == PROJECT_NAME).order_by(m.Project.created_at).limit(1))


async def _archive_partial(project_id: UUID) -> None:
    try:
        async with session() as s, s.begin():
            project = await s.get(m.Project, project_id)
            if project is not None:
                project.status = "archived"
    except Exception:  # the original failure matters more
        logger.warning("could not archive a partial demo project", exc_info=True)


@asynccontextmanager
async def _timed(stage: str) -> AsyncIterator[None]:
    started = time.perf_counter()
    yield
    seconds = time.perf_counter() - started
    logger.info("demo seed stage %s: %.2f s", stage, seconds, extra={"stage": stage, "seconds": round(seconds, 2)})


async def _build(user_id: UUID, project_id: UUID) -> None:
    brief, kit = fx.load("campaign_brief.json"), fx.load("brand_kit.json")
    original = fx.load("creative_mh_original.json")
    async with session() as s, s.begin():
        workspace_id = await ensure_personal_workspace(s, user_id)
    async with _timed("core rows"):
        campaign_id = await _core_rows(user_id, project_id, workspace_id, brief, kit, original)
    async with _timed("assets"):
        assets = await _store_assets(user_id, project_id, original)
        async with session() as s, s.begin():
            await desk.link_kit_assets(s, project_id)
    async with _timed("x-ray"):
        scenes = await _seed_xray(user_id, project_id, campaign_id, assets, original)
    async with _timed("conflicts"), session() as s, s.begin():
        await claim_service.sync_conflicts(s, workspace_id, mode="demo")  # the genuine conflicts, recorded for this workspace
    async with _timed("version tree"):
        tree = await _version_tree(user_id, campaign_id, original, scenes)
    async with _timed("audience and readiness"):
        await _audience_and_readiness(user_id, workspace_id, campaign_id, original, scenes, tree)
    async with _timed("pulse"):
        await pulse.load_sample(user_id, campaign_id)
    # Tier 3 features, already populated in the demo (each hook is idempotent, offline and refuses live projects).
    from app.services import delivery_demo, digest_demo, lens_t3, pulse_t3_demo, usage  # noqa: PLC0415  (avoid import cycles)

    async with _timed("launch delivery"):
        await delivery_demo.seed_launch_delivery(user_id, campaign_id)
    async with _timed("pulse alerts, fatigue, predicted vs actual"):
        await pulse_t3_demo.seed_pulse_t3(user_id, campaign_id)
    async with _timed("comment pulse and weekly digest"):
        await digest_demo.seed_comment_pulse_and_digests(user_id, campaign_id)
    async with _timed("trend radar and category shelf"):
        await lens_t3.seed_lens_t3_demo(user_id, campaign_id)
    async with _timed("proof report"):
        await proof_reports.create_report(user_id, campaign_id, ProofReportCreate(
            title="Aamod Festive Tin, Diwali 2027: Proof Report (demonstration)", region_codes=list(REGIONS)))
    async with session() as s, s.begin():
        await usage.seed_demo_usage(s, project_id)
        await record_audit(s, action="demo.seed", target_type="project", target_id=str(project_id), workspace_id=workspace_id,
                           actor_user_id=user_id, detail={"journey": "aamod", "fixture": FIXTURE_LABEL})


# --- reference data and the shared demo claims ----------------------------------------------------------------------


async def prepare_shared_data() -> None:
    """Reference data and the shared demo claims: once per database, then a no-op. `python -m scripts.seed_demo_claims` runs
    it at deploy time so that the first user to press "Try the demo" does not pay for it."""
    await _ensure_reference_data()
    await _ensure_demo_claims()


async def _ensure_reference_data() -> None:
    async with session() as s, s.begin():
        if await s.scalar(select(m.Region.id).where(m.Region.code == ORIGIN)) is None:
            await seed_reference_data(s)  # a fresh database (tests, first run); production is seeded by the deploy step


def _keep(code: str, claim: Any) -> bool:
    """The demo's claim selection. The census gives ~20 per-language rows and the holiday calendar ~30 dates per state, and the
    Studio offers a model only its first 24 claims (language first), so the full set would hide the festival claims the story
    rests on. Kept: the official and principal language, the state's own language and Hindi (the West Bengal Hindi share is one
    of the two genuine conflicts), and the public holidays inside the campaign dates. Everything else is kept as it is."""
    if claim.category == "language":
        return claim.attribute in ("official_language", "principal_language") or claim.scope.language in (PRIMARY_LANGUAGE[code], "hi")
    if claim.category == "moment" and claim.attribute == "public_holiday_date":
        hit = _DATE.search(claim.value_text)
        return bool(hit) and CAMPAIGN_WINDOW[0] <= date.fromisoformat(hit.group(1)) <= CAMPAIGN_WINDOW[1]
    return True


async def _ensure_demo_claims() -> None:
    """Fixture claims for the four states, stored once for everyone: `workspace_id` NULL (shared) and `mode = demo`, so a
    live project never reads them (claims are filtered by the project's mode) and a re-seed adds nothing."""
    async with _lock("claims"):
        async with read_session() as s:
            have = set((await s.execute(
                select(m.Region.code).join(m.Claim, m.Claim.region_id == m.Region.id)
                .where(m.Claim.workspace_id.is_(None), m.Claim.mode == "demo").distinct())).scalars())
        missing = [code for code in REGIONS if code not in have]
        if not missing:
            return
        builder = RegionProfileBuilder(build_culture_service(get_settings(), mode="demo"))
        for code in missing:  # the fixture source: no network, fixed timestamps
            profile = await builder.build(code, years=(2027,), today=date(2026, 11, 17))
            async with session() as s, s.begin():
                await claim_service.upsert_claims(s, [c for c in profile.all_claims() if _keep(code, c)], workspace_id=None,
                                                  mode="demo", now=FIXTURE_TIME)


# --- project, brand, brief, glossary ----------------------------------------------------------------------------------


async def _core_rows(user_id: UUID, project_id: UUID, workspace_id: UUID, brief: dict, kit: dict, original: dict) -> UUID:
    now = utcnow()
    campaign_id = uuid4()
    video = original["creatives"][0]
    copy = {e["id"]: e["value"] for e in video["elements"]}
    async with session() as s, s.begin():
        s.add(m.Project(id=project_id, owner_id=user_id, workspace_id=workspace_id, name=PROJECT_NAME, mode="demo", status="active",
                        target_markets=[MARKET], last_activity_at=now, created_at=now, updated_at=now))
        await s.flush()
        s.add(m.BrandKit(id=uuid4(), project_id=project_id, name="Aamod", created_at=now, updated_at=now))
        s.add(m.Campaign(id=campaign_id, project_id=project_id, name=brief["name"][:120], campaign_type="advertisement",
                         target_markets=[MARKET], evaluation_criteria=DEFAULT_EVALUATION_CRITERIA.model_dump(),
                         created_at=now, updated_at=now))
        await s.flush()
        s.add(m.CampaignVersion(id=uuid4(), campaign_id=campaign_id, project_id=project_id, version_number=1, created_at=now, content={
            "headline": copy["mh-vid-s1-headline"], "body": copy["mh-vid-s3-headline"],
            "call_to_action": f'{copy["mh-vid-cta-hook"]} · {copy["mh-vid-cta-button"]}'[:200],
            "reference_terms": ["फराळ", "भाऊबीज", "आकाशकंदील"]}))
        await s.flush()
        await desk.apply_demo_brief_and_brand(s, project_id=project_id, campaign_id=campaign_id, brief=brief, brand_kit=kit)
        await _demo_brand_extras(s, project_id=project_id, campaign_id=campaign_id, brief=brief, brand_kit=kit)
        _glossary(s, project_id, user_id, fx.load("brand_glossary.json"), now)
    return campaign_id


async def _demo_brand_extras(s: Any, *, project_id: UUID, campaign_id: UUID, brief: dict, brand_kit: dict) -> None:
    """Brand record and project fields the demo reads beyond the Desk seam (preferred and prohibited terms, positioning, audience)."""
    project, campaign = await s.get(m.Project, project_id), await s.get(m.Campaign, campaign_id)
    brand = (await s.execute(select(m.BrandKit).where(m.BrandKit.project_id == project_id))).scalar_one()
    product, tone = brief["product"], brand_kit["tone_of_voice"]
    project.description = f"{DEMO_LABEL} {product['name']}: {brief['primary_message']}"[:1000]
    project.objective = brief["objective"][:300]
    campaign.objective = brief["objective"][:300]
    brand.name, brand.description = brand_kit["name"], f"{DEMO_LABEL} {brand_kit['description']}"[:1000]
    brand.positioning = f"{brand_kit['category']}. {product['description']}"[:1000]
    brand.voice, brand.communication_style = list(tone["traits"]), tone["summary"][:1000]
    brand.target_audience = brief["target_audience"]["summary"][:300]
    brand.audience_preferences = (f"Ages {', '.join(brief['target_audience']['age_bands'])}, city tiers "
                                  f"{', '.join(brief['target_audience']['city_tiers'])}. {brief['target_audience']['targeting_exclusions']}")[:1000]
    brand.preferred_terms = ["gift", "home-style", "delivered before the festival"]
    brand.prohibited_terms = ["No. 1", "number one", "world's best"]  # superiority claims: the Brand Kit's claims policy
    brand.protected_terms = [t["term"] for t in brand_kit["protected_terms"]]
    brand.approved_examples = [{"text": brand_kit["tagline"]["text"], "note": "Approved tagline; never translated."}]
    brand.constraints = [*brief["constraints"][:3], *(item[:300] for item in brand_kit["claims_policy"]["forbidden"]),
                         "Never borrow one region's festival words for another region."]
    brand.updated_at = campaign.updated_at = project.updated_at = utcnow()


def glossary_rows(data: dict) -> list[dict[str, Any]]:
    """The Brand Glossary as `glossary_terms` rows (without ids): per language and script, with pronunciation and notes."""
    language_of = {"Deva": "mr", "Taml": "ta", "Mlym": "ml", "Beng": "bn"}
    rows: list[dict[str, Any]] = []
    for entry in data["entries"]:
        notes = entry.get("language_notes", {})
        fixed = entry["translate"] is False
        guide = (entry.get("pronunciation") or {}).get("guide")
        if fixed:  # protected, never translated; one row for every language, then the approved spelling per script
            rows.append(dict(term=entry["term"], language="*", protected=True, never_translate=True, notes=notes.get("all"), pronunciation=guide))
        for script, spelling in entry["spellings"].items():
            language = language_of.get(script)
            if language is not None:
                rows.append(dict(term=entry["term"], language=language, script=script, approved_spelling=spelling, protected=fixed,
                                 never_translate=fixed, pronunciation=guide, notes=notes.get(language) or notes.get("all"),
                                 **({"preferred_translation": spelling} if entry["type"] == "preferred_translation" else {})))
    return rows


def _glossary(s: Any, project_id: UUID, user_id: UUID, data: dict, now: datetime) -> None:
    for row in glossary_rows(data):
        s.add(m.GlossaryTerm(id=uuid4(), project_id=project_id, term_key=row["term"].casefold(), created_by=user_id, created_at=now,
                             updated_at=now, **row))


# --- assets ---------------------------------------------------------------------------------------------------------


async def _store_assets(user_id: UUID, project_id: UUID, original: dict) -> dict[str, UUID]:
    """The film, the key visual, the clean scene images and the derived keyframes and thumbnail, as stored assets."""
    video, keyvisual = original["creatives"]
    scenes = [s for s in video["scenes"] if s.get("plate")]
    srt = fx.file_bytes(video["captions"]["path"])
    parsed = sidecar_text.parse_sidecar(srt)
    media_info = {"container": "mov,mp4,m4a,3gp,3g2,mj2", "tags": {}, "tags_redacted": {}, "tags_dropped": [], "sidecar": {
        "format": parsed.format, "text": parsed.text, "segments": parsed.segments, "redacted": parsed.redacted}}
    specs: list[dict[str, Any]] = [
        dict(name="video", path=video["asset"]["path"], filename="aamod-mh-original.mp4", kind="video", type="video/mp4",
             duration_ms=video["asset"]["duration_ms"], width=1080, height=1920, info=media_info, rights=True, processing="ready"),
        dict(name="keyvisual", path=keyvisual["asset"]["path"], filename="aamod-mh-key-visual.png", kind="image", type="image/png",
             width=1080, height=1350),
        dict(name="kv-plate", path=keyvisual["plate"]["path"], filename="aamod-mh-key-visual-plate.jpg", kind="image",
             type="image/jpeg", width=1080, height=1350),
        *(dict(name=f"plate-{s['id']}", path=s["plate"], filename=s["plate"].rsplit("/", 1)[-1], kind="image", type="image/jpeg")
          for s in scenes),
        *(dict(name=f"kf-{sid}", path=f"creative/mh_original/keyframes/{sid}.jpg", filename=f"{sid}-keyframe.jpg", kind="image",
               type="image/jpeg", width=540, height=960, parent="video", role="keyframe", at=ms) for sid, ms in fxray.FRAME_MS.items()),
        dict(name="thumb", path="creative/mh_original/keyframes/mh-s1.jpg", filename="aamod-mh-original-thumbnail.jpg", kind="image",
             type="image/jpeg", width=540, height=960, parent="video", role="thumbnail", at=0),
        # Brand Kit images, named like the fixture paths so the Desk Brand Kit links them (desk.link_kit_assets)
        *(dict(name=f"brand-{stem}", path=f"brand/{stem}.png", filename=f"{stem}.png", kind="image", type="image/png")
          for stem in ("logo", "logo_mark", "logo_reversed", "logo_stacked", "pack")),
    ]
    now = utcnow()
    ids = {spec["name"]: uuid4() for spec in specs}
    data = {spec["name"]: fx.file_bytes(spec["path"]) for spec in specs}
    keys = {name: blobs.object_key(user_id, asset_id) for name, asset_id in ids.items()}
    stored: list[str] = []
    try:
        await asyncio.gather(*(blobs.store(keys[spec["name"]], data[spec["name"]], spec["type"]) for spec in specs))
        stored = list(keys.values())
        async with session() as s, s.begin():
            for spec in specs:  # the film first: derived files point at it
                name = spec["name"]
                row = m.Asset(
                    id=ids[name], project_id=project_id, kind=spec["kind"], filename=spec["filename"], content_type=spec["type"],
                    size_bytes=len(data[name]), sha256=hashlib.sha256(data[name]).hexdigest(), storage_name=keys[name],
                    created_at=now, processing_status=spec.get("processing", "not_required"), rights_confirmed=spec.get("rights", False),
                    rights_confirmed_at=now if spec.get("rights") else None, duration_ms=spec.get("duration_ms"), width=spec.get("width"),
                    height=spec.get("height"), parent_asset_id=ids[spec["parent"]] if "parent" in spec else None,
                    derived_role=spec.get("role"), derived_at_ms=spec.get("at"), media_info=spec.get("info"))
                s.add(row)
                await s.flush()
                blobs.attach(s, row, data[name])
    except BaseException:
        await blobs.discard(stored)
        raise
    return ids


# --- Creative X-Ray: the saved reading of the film and the key visual -------------------------------------------------


def scene_uuid(project_id: UUID, key: str) -> UUID:
    """Stable id of a scene (fixture scene id) in one project, so elements and findings can point at it."""
    return uuid5(project_id, f"aamod-scene:{key}")


async def _seed_xray(user_id: UUID, project_id: UUID, campaign_id: UUID, assets: dict[str, UUID], original: dict) -> dict[str, Any]:
    video, keyvisual = original["creatives"]
    now = utcnow()
    transcript = [TranscriptSegment(id=f"t{n}", start_ms=t["start_ms"], end_ms=t["end_ms"], text=t["text"], source="transcription",
                                    language="mr") for n, t in enumerate(video["transcript"], 1)]
    out: dict[str, Any] = {}
    for creative, asset_key, label, kind in ((video, "video", "Maharashtra film (Marathi), 29 s", "video"),
                                             (keyvisual, "keyvisual", "Maharashtra key visual (Marathi), feed post", "image")):
        keys = fxray.scene_keys(creative)
        frames, observations = [], {}
        for n, key in enumerate(keys, 1):
            frame_id = f"f{n}"
            asset = assets[f"kf-{key}"] if kind == "video" else None
            frames.append(PreparedFrame(frame_id, fxray.FRAME_MS.get(key, 0), asset, "image/jpeg", b""))
            observations[frame_id] = [
                VisualObservation(id=f"{frame_id}.v{i}", asset_id=asset or assets["keyvisual"], kind=k, description=d, location=w)  # type: ignore[arg-type]
                for i, (k, d, w) in enumerate(fxray.frame_lines(creative, key), 1)]
        drafts = [SceneOut.model_validate(fxray.scene_draft(creative, key, f"f{n}")) for n, key in enumerate(keys, 1)]
        built, dropped, _ = _build_scenes(drafts, kind, creative, frames, observations, transcript if kind == "video" else [])
        for scene, key in zip(built, keys):
            scene.id = scene_uuid(project_id, key)
            scene.limitations = [*scene.limitations, FIXTURE_LABEL]
        run_id, creative_id = uuid4(), uuid4()
        probe = MediaProbe(kind=kind, container="mov,mp4,m4a,3gp,3g2,mj2" if kind == "video" else "image/png",  # type: ignore[arg-type]
                           duration_ms=creative["asset"].get("duration_ms"), width=creative["asset"]["width"],
                           height=creative["asset"]["height"], fps=creative["asset"].get("fps"), has_video=kind == "video",
                           has_audio=kind == "video", video_codec="h264" if kind == "video" else None,
                           audio_codec="aac" if kind == "video" else None)
        outcome = _outcome(probe, frames, observations, transcript if kind == "video" else [], built, dropped, kind)
        async with session() as s, s.begin():
            s.add(m.CreativeAsset(id=creative_id, project_id=project_id, campaign_id=campaign_id, asset_id=assets[asset_key],
                                  kind=kind, label=label, region_code=ORIGIN, language="mr", latest_run_id=None, current_run_id=None,
                                  created_at=now, updated_at=now))
            run = m.AgentRun(
                id=run_id, project_id=project_id, campaign_id=campaign_id, run_type="creative_xray", status="completed", mode="demo",
                inputs={"creative_asset_id": str(creative_id), "fixture": FIXTURE_LABEL}, created_at=now, started_at=now,
                completed_at=now, created_by=user_id, steps=[st.model_dump(mode="json") for st in outcome.steps],
                progress=RunProgress(stage="completed", completed_steps=5, total_steps=5,
                                     message="Complete. (demo fixtures)").model_dump())
            s.add(run)
            await s.flush()
            payload, ref = await xray.persist(s, run, outcome, [], now)
            run.result, run.result_ref = payload, RunResultRef(resource=ref[0], ids=ref[1], url=ref[2]).model_dump(mode="json")  # type: ignore[arg-type]
        out[kind] = {"creative_id": creative_id, "run_id": run_id, "scenes": {key: scene_uuid(project_id, key) for key in keys},
                     "bounds": {s.id: (s.start_ms, s.end_ms) for s in built}}
    return out


def _build_scenes(drafts: list[SceneOut], kind: str, creative: dict, frames: list[PreparedFrame], observations: dict,
                  transcript: list[TranscriptSegment]) -> tuple[list[Any], dict[str, int], list[str]]:
    """The real X-Ray verification over the fixture drafts: nothing unverifiable survives."""
    from app.workflows.xray import build_scenes

    return build_scenes(drafts, kind=kind, duration_ms=creative["asset"].get("duration_ms"), frames=frames, observations=observations,
                        transcript=transcript, music_mood=None, visual_ok=True)


def _outcome(probe: MediaProbe, frames: list[PreparedFrame], observations: dict, transcript: list[TranscriptSegment],
             scenes: list[Any], dropped: dict[str, int], kind: str) -> Any:
    from app.workflows.xray import FrameOut, XRayOutcome

    note = "Saved demonstration result of a fictional creative: no model was called when it was loaded."
    step = lambda stage, agent: StepTrace(stage=stage, agent=agent, status="completed", provider="fixture", model_id=MODEL,  # noqa: E731
                                          prompt_version="xray-scenes-v1" if stage == "structuring_scenes" else None)
    return XRayOutcome(
        status="completed", probe=probe,
        transcribe=TranscribeStatus(status="transcribed" if kind == "video" else "not_applicable", provider="fixture" if kind == "video" else None,
                                    model_id=MODEL if kind == "video" else None,
                                    message=("Saved demonstration result: a transcription round-trip of the generated voice-over matched all six lines. "
                                             "Not reviewed by a native speaker.") if kind == "video" else "Images have no audio."),
        vision=VisionStatus(status="analyzed", provider="fixture", model_id=MODEL,
                            message="Demonstration fixture: the frame observations were written from the creative's own elements; no vision model was called."),
        frames=[FrameOut(id=f.frame_id, timestamp_ms=f.timestamp_ms, asset_id=f.asset_id, observations=observations[f.frame_id])
                for f in frames],
        transcript=transcript, sidecar_notes=None, scenes=scenes, dropped=dropped,
        limitations=[FIXTURE_LABEL, note, "Interpretations are a demonstration model's cultural reading, not facts."],
        steps=[step("probing_media", "cultural_xray"), step("extracting_media", "cultural_xray"), step("transcribing", "cultural_xray"),
               step("observing_frames", "vision"), step("structuring_scenes", "cultural_xray")])


# --- the version tree --------------------------------------------------------------------------------------------------


def _elements(original: dict, scenes: dict[str, Any]) -> list[vs.CreativeElement]:
    """Every element of the film and the key visual, with scene ids that point at the stored X-Ray scenes."""
    out = []
    for creative, kind in zip(original["creatives"], ("video", "image")):
        for e in creative["elements"]:
            scene = scenes[kind]["scenes"].get(e["scene_id"]) if e.get("scene_id") else (scenes[kind]["scenes"]["kv"] if kind == "image" else None)
            out.append(vs.CreativeElement(id=e["id"], kind=e["kind"], value=e["value"], language=e["language"], script=e["script"],
                                          bbox=[float(x) for x in e["bbox"]] if e["bbox"] else None,
                                          scene_id=str(scene) if scene else None, locked=e["locked"]))
    return out


async def _wait(model: Any, run_id: UUID, what: str) -> Any:
    """Poll a run row until it ends. Runs execute in this process; a run that does not complete is a seeding failure."""
    deadline = time.monotonic() + WAIT_LIMIT_SECONDS
    while time.monotonic() < deadline:
        async with read_session() as s:
            row = await s.get(model, run_id)
        if row is not None and row.status in TERMINAL:
            if row.status != "completed":
                raise RuntimeError(f"demo seed: the {what} run ended {row.status}: {row.error}")
            return row
        await asyncio.sleep(POLL_SECONDS)
    raise RuntimeError(f"demo seed: the {what} run did not finish in {WAIT_LIMIT_SECONDS} s")


async def _version_tree(user_id: UUID, campaign_id: UUID, original: dict, scenes: dict[str, Any]) -> dict[str, Any]:
    """v1 (Maharashtra, Marathi), the locks, and per target state: a transcreation, Tweak Chips and a hand edit."""
    elements = _elements(original, scenes)
    locked = [e.id for e in elements if e.locked]  # the fixture's never-change zones
    root = await versions.create_version(user_id, campaign_id, vs.VersionCreate(
        label="Original · Maharashtra (Marathi)", elements=elements, region_code=ORIGIN, language="mr"))
    for element_id in locked:  # the never-change zones: the logo, the tin (pack and in every scene) and the tagline
        await versions.set_lock(user_id, campaign_id, element_id, vs.LockCreate(
            reason="Brand Kit never-change zone: logo, Aamod Festive Tin and tagline stay unchanged in every region."))
    async with session() as s, s.begin():  # the root was made before any lock existed: it shows the zones it was authored with
        node = await s.get(m.VersionNode, root.id)
        node.elements = [{**e, "locked": e["id"] in locked} for e in node.elements]
    tree: dict[str, Any] = {"root": root.id, "locked": locked, "regions": {}}
    texts = [e for e in root.elements if e.kind in fx.TRANSCREATE_KINDS and isinstance(e.value, str) and e.id not in locked
             and e.id not in fx.SMALL_PRINT_IDS and e.value != "Fictional brand · Omnicult demo creative"]
    for plan in fx.ADAPTATIONS:
        accepted = await transcreate.start_transcreate(user_id, campaign_id, vs.TranscreateRequest(
            version_id=root.id, region_code=plan.region, language=plan.language, element_ids=[e.id for e in texts],
            tone=vs.Tone(**plan.tone)))
        run = await _wait(m.AgentRun, accepted.run_id, f"{plan.name} transcreate")
        current = UUID(run.result["version_id"])
        cited = set(await _operation_claims(campaign_id, current))
        chip_ids: list[UUID] = []
        if plan.festival_term is not None:  # the delivery promise names the festival day the region's evidence supports
            for element_id in fx.CHIP_ELEMENT_IDS:
                proposed = await chips.generate_chips(user_id, campaign_id, vs.ChipGenerate(
                    version_id=current, element_id=element_id, region_code=plan.region, max_chips=1))
                if not proposed.chips:
                    raise RuntimeError(f"demo seed: no Tweak Chip for {element_id} in {plan.region}: {proposed.notes}")
                applied = await chips.apply_chip(user_id, campaign_id, proposed.chips[0].id, vs.ChipApply())
                current, cited = applied.version.id, cited | set(applied.operation.claim_ids)
                chip_ids.append(applied.chip.id)
        edited = await versions.apply_operation(user_id, campaign_id, vs.OperationRequest(
            version_id=current, label=f"{plan.name}: unsourced claim replaced"[:80],
            operation=vs.ManualEdit(kind="manual_edit", edits=[
                vs.ElementEdit(element_id=i, set={"value": plan.small_print, "language": plan.language, "script": plan.script})
                for i in fx.SMALL_PRINT_IDS]),
            reason="Removed the unsourced 'best faral tin' superiority claim from the small print and put the net weight there, a true "
                   "product fact the Brand Kit's claims policy allows."))
        tree["regions"][plan.region] = {"final": edited.version.id, "transcreate_run": run.id, "chips": chip_ids, "cited": cited}
    return tree


async def _operation_claims(campaign_id: UUID, version_id: UUID) -> list[UUID]:
    async with read_session() as s:
        ops = (await s.execute(select(m.Operation).where(m.Operation.campaign_id == campaign_id,
                                                         m.Operation.result_version_id == version_id))).scalars().all()
    return [UUID(c) for op in ops for c in op.claim_ids]


# --- Audience Lab, readiness ---------------------------------------------------------------------------------------------


def _content_of(elements: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {e["id"]: e["value"] for e in elements}
    return {"headline": by_id["mh-vid-s1-headline"], "body": by_id["mh-kv-sub"],
            "call_to_action": f'{by_id["mh-vid-cta-hook"]} · {by_id["mh-vid-cta-button"]}'[:200], "reference_terms": []}


def _risk_elements(node: m.VersionNode, transcript: str) -> list[aus.CreativeElementIn]:
    out = []
    for e in node.elements:
        if e["kind"] in ("headline", "body", "cta", "tagline", "caption") and isinstance(e["value"], str):
            value = e["value"]
        elif e["kind"] == "voiceover":
            value = transcript  # what is spoken is checked too; the stored element only points at the audio file
        else:
            continue
        out.append(aus.CreativeElementIn(id=e["id"], kind=e["kind"], value=value, language=e["language"], script=e["script"],
                                         bbox=e["bbox"], scene_id=e["scene_id"], locked=e["locked"]))
    return out


async def _audience_and_readiness(user_id: UUID, workspace_id: UUID, campaign_id: UUID, original: dict, scenes: dict[str, Any],
                                  tree: dict[str, Any]) -> None:
    video = original["creatives"][0]
    spoken = " ".join(t["text"] for t in video["transcript"])
    scene_rows = [aus.CreativeSceneIn(id=str(scenes["video"]["scenes"][s["id"]]), start_ms=s["start_ms"], end_ms=s["end_ms"],
                                      summary=s["description"][:300]) for s in video["scenes"]]
    scene_rows.append(aus.CreativeSceneIn(id=str(scenes["image"]["scenes"]["kv"]), start_ms=0, end_ms=None,
                                          summary="Feed key visual: Diwali snack spread, headline, pack, call to action and tagline."))
    targets = [(ORIGIN, tree["root"], "Original · Maharashtra", set(), None, fx.ORIGINAL_FESTIVAL_TERM)]
    targets += [(p.region, tree["regions"][p.region]["final"], f"{p.name} · {p.language_name}", tree["regions"][p.region]["cited"],
                 tree["regions"][p.region]["transcreate_run"], p.festival_term) for p in fx.ADAPTATIONS]
    scratch: list[UUID] = []  # content versions made only so Quick Read can read each version's text; removed afterwards
    run_ids: list[UUID] = []
    sessions: list[lab_t3.DemoVersion] = []
    try:
        for code, node_id, label, cited, transcreate_run, festival in targets:
            async with read_session() as s:
                node = await s.get(m.VersionNode, node_id)
            content_id = uuid4()
            scratch.append(content_id)
            async with session() as s, s.begin():
                latest = max((await s.execute(select(m.CampaignVersion.version_number).where(m.CampaignVersion.campaign_id == campaign_id))).scalars())
                s.add(m.CampaignVersion(id=content_id, campaign_id=campaign_id, project_id=node.project_id, version_number=latest + 1,
                                        content=_content_of(node.elements), created_at=utcnow()))
            quick = await audience.start_quick_read(user_id, campaign_id, aus.QuickReadCreate(
                region_code=code, content_version_id=content_id, version_ref=str(node_id), intended_message=fx.BRIEF_PRIMARY_MESSAGE,
                size=12, seed=42))
            risk = await audience.start_risk_check(user_id, campaign_id, aus.RiskCheckCreate(
                region_code=code, elements=_risk_elements(node, spoken), scenes=scene_rows, version_ref=str(node_id),
                product_category="packaged festive sweets and snacks"))
            run_ids += [quick.run_id, risk.run_id]
            sessions.append(lab_t3.DemoVersion(region_code=code, quick_read_run_id=quick.run_id, version_ref=str(node_id), creative=_content_of(node.elements)))
            quick_run = await _wait(m.AudienceRun, quick.run_id, f"{label} Quick Read")
            risk_run = await _wait(m.AudienceRun, risk.run_id, f"{label} Risk Check")
            observations = await _observations(user_id, workspace_id, campaign_id, code, node, quick_run, risk_run, transcreate_run,
                                               cited, festival, tree["root"])
            await launch.compute_readiness(user_id, campaign_id, ls.ReadinessRequest(
                region_code=code, version_id=node_id, label=label[:60], observations=observations))
    finally:
        async with session() as s, s.begin():  # the runs keep `version_ref`; the campaign's content stays the original (v1)
            await s.execute(update(m.AudienceRun).where(m.AudienceRun.id.in_(run_ids)).values(content_version_id=None))
            await s.execute(delete(m.CampaignVersion).where(m.CampaignVersion.id.in_(scratch)))
    # Live Focus Group, Buzz Simulator and Message Check, from fixtures (lab-t3): one finished session of each kind on these panels.
    await lab_t3.seed_demo_sessions(user_id, campaign_id, sessions, intended_message=fx.BRIEF_PRIMARY_MESSAGE)


async def _observations(user_id: UUID, workspace_id: UUID, campaign_id: UUID, code: str, node: m.VersionNode, quick_run: m.AudienceRun,
                        risk_run: m.AudienceRun, transcreate_run: UUID | None, cited: set[UUID], festival: str | None,
                        root_id: UUID) -> ls.VersionObservations:
    """What was observed about one version in one region, read from what the seed stored. Verdicts come from the rules."""
    async with read_session() as s:
        panel = (await s.execute(select(m.PanelParticipant).where(m.PanelParticipant.run_id == quick_run.id))).scalars().all()
        findings = (await s.execute(select(m.RiskFindingRow).where(m.RiskFindingRow.run_id == risk_run.id)
                                    .order_by(m.RiskFindingRow.ordinal))).scalars().all()
        root = await s.get(m.VersionNode, root_id)
        operations = (await s.execute(select(m.Operation).where(m.Operation.campaign_id == campaign_id,
                                                                m.Operation.kind == "transcreate"))).scalars().all()
    operation = next((o for o in operations if transcreate_run and o.params.get("run_id") == str(transcreate_run)), None)
    replies = [p.response for p in panel if p.response]
    quick = ls.QuickReadObservation(
        respondents=len(replies), understood=sum(r["message"]["survival"] == "understood" for r in replies),
        confused=sum(r["message"]["survival"] == "misunderstood" for r in replies),
        positive=sum(r["sentiment"] == "positive" for r in replies), negative=sum(r["sentiment"] == "negative" for r in replies),
        relevant=sum(r["ratings"]["cultural_relevance"] >= 4 for r in replies), concerned=sum(bool(r["regional_concerns"]) for r in replies))
    risk = ls.RiskCheckObservation(run_id=risk_run.id, findings=[ls.RiskFindingInput(
        id=f"F{f.ordinal + 1}", severity=f.severity, category=f.category, status=f.status, blocks_go=f.blocks_go,  # type: ignore[arg-type]
        source=f.source, summary=f.observation[:300], claim_ids=[UUID(c) for c in f.claim_ids],  # type: ignore[arg-type]
        anchor=Anchor.model_validate(f.anchor)) for f in findings])
    lines = (operation.params["lines"] if operation else [])
    transcreation = ls.TranscreationObservation(
        lines_checked=len(lines), glossary_violation_lines=sum(bool(x["term_checks"]["missing_in_copy"] or x["term_checks"]["missing_in_back_translation"]
                                                                  or x["term_checks"]["prohibited_in_copy"]) for x in lines),
        prohibited_term_lines=sum(bool(x["term_checks"]["prohibited_in_copy"]) for x in lines),
        script_error_lines=sum(not x["script_check"]["ok"] for x in lines)) if lines else None  # back-translation is not checked in code
    profile = await claim_service.build_region_profile(user_id, workspace_id, code, mode="demo")
    meter = profile.meter
    conflicts, _ = await claim_service.list_conflicts(user_id, workspace_id, region_code=code, status=None, mode="demo", limit=100, offset=0)
    open_conflicts = [ls.OpenConflictInput(
        conflict_id=c.id, claim_ids=[c.claim_a.id, c.claim_b.id], relied_on=bool({c.claim_a.id, c.claim_b.id} & cited),
        status=c.status, summary=c.reason[:300]) for c in conflicts if c.status != "resolved"]  # type: ignore[arg-type]
    cta = {e["id"]: e["value"] for e in node.elements}["mh-vid-cta-hook"]
    held = all(next(x["value"] for x in node.elements if x["id"] == e["id"]) == e["value"] for e in root.elements if e["locked"])
    named = festival is not None and festival in cta
    return ls.VersionObservations(
        provenance=ls.Provenance(model_id=MODEL, prompt_version="quick-read-v1, risk-check-v1", criteria_version="panel-12-seed-42",
                                 evidence_snapshot="demo-fixture-2026-11-17", run_ids=[quick_run.id, risk_run.id]),
        quick_read=quick, risk_check=risk, transcreation=transcreation, open_conflicts=open_conflicts,
        evidence_meter=ls.EvidenceMeterObservation(
            strength=meter.strength, claims=meter.claims, supported_claims=meter.supported_claims,  # type: ignore[arg-type]
            open_conflicts=meter.open_conflicts, stale_claims=meter.stale_claims),
        objective_checks=[
            ls.ObjectiveCheck(id="festival-delivery-promise", primary=True, status="met" if named else "partly_met",
                              statement="The call to action promises delivery before the region's festival day and names a day its evidence supports."),
            ls.ObjectiveCheck(id="brand-zones-held", status="met" if held else "not_met",
                              statement="The logo, the Aamod Festive Tin and the English tagline are unchanged.")])
