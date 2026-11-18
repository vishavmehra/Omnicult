"""Voice Director (feature 26 and the Command Bar's typed Voice Director): plan an instruction, confirm, apply.

`create_plan` makes one structured model call (through the gateway, with a prompt version), validates every step in code
(app.agents.direct) and stores the plan, with the planning call recorded as a `voice_direct` run. `apply_plan` runs only
the steps a person confirmed, only steps the server stored, in plan order, through the SAME services the Studio UI uses
(operations, chips, locks, restore, Transcreate): a lock set since the plan was made still refuses the step (409), and every
change is a new version made by actor `ai` with the instruction as its reason. Voice input is transcribed first
(`transcribe`), shown to the person for correction, and only then planned: the audio is never stored.
"""

import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import direct
from app.agents._common import DEMO_OUTPUT_NOTE
from app.agents.direct import ChipRef, PlanContext, VersionRef
from app.core.config import get_settings
from app.core.errors import AppError, Conflict, ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.llm.gateway import LLMError
from app.media.ffmpeg import MediaProcessingFailed, extract_audio
from app.schemas import direct as v
from app.schemas import versions as vs
from app.schemas.common import ErrorDetail
from app.schemas.runs import RunProgress, RunResultRef
from app.services import chips, regions, transcreate, versions
from app.services import studio_context as ctx
from app.services.ai_guard import guarded_ai_call
from app.services.audit import record_audit
from app.services.common import conflict, not_found, paginate
from app.services.results import API
from app.services.runs import brand_of, merge_terms
from app.services.versions import active_locks, campaign_for, newest_node, node_in, raise_if_rejected, record_operation
from app.studio.engine import Edit, OpSpec

MAX_CLIP_BYTES = 4 * 1024 * 1024  # a 60 second recording from a browser is well under 1 MB
MAX_CLIP_SECONDS = 60.0
MAX_TRANSCRIPT_CHARS = 500  # the instruction limit, so a transcript always fits the next field
CLAIM_STALE = timedelta(seconds=120)  # a step claimed longer ago than this was left by a request that died
LISTED_VERSIONS = 14
LISTED_CHIPS = 12
REGION_COUNTRY = "IN"  # the Country Pack the reference lists belong to


# --- voice: transcription ------------------------------------------------------------------------------------------


def _is_clip(data: bytes) -> bool:
    """WAV, WebM, Ogg or MP4/M4A by magic bytes: what MediaRecorder produces in Chrome, Firefox and Safari."""
    return (
        data[:4] == b"RIFF" and data[8:12] == b"WAVE" or data.startswith(b"\x1a\x45\xdf\xa3") or data.startswith(b"OggS")
        or data[4:8] == b"ftyp"
    )


def _transcript(status: str, text: str = "", *, message: str | None = None, language: str | None = None, duration_ms: int | None = None,
                provider: str | None = None, model_id: str | None = None) -> v.DirectTranscript:
    return v.DirectTranscript(
        status=status, transcript=text, message=message, language=language, duration_ms=duration_ms,  # type: ignore[arg-type]
        provider=provider, model_id=model_id,
    )


async def transcribe(user_id: UUID, campaign_id: UUID, data: bytes, language: str | None) -> v.DirectTranscript:
    """Speech to text for one short clip. A demo project never calls a provider, so it says so instead of inventing text."""
    async with read_session() as s:
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
    if project.mode == "demo":
        return _transcript("unavailable", message="A demo project never calls a model provider, so there is no transcription. Type the instruction instead.")
    if not data or len(data) > MAX_CLIP_BYTES or not _is_clip(data):
        raise ValidationFailed("The recording must be a WAV, WebM, Ogg or MP4 clip of at most 4 MB.",
                               details=[ErrorDetail(field="file", message="Unsupported or oversized audio.")])
    from app import workflows  # resolved at call time, so tests can substitute the workflow dependencies

    capability = workflows.build_workflow_deps(project.mode, get_settings()).transcribe
    if capability is None or not capability.is_configured():
        return _transcript("unavailable", message="Speech transcription is not configured on this server. Type the instruction instead.")
    with tempfile.TemporaryDirectory() as folder:
        source, out = Path(folder, "clip.bin"), Path(folder, "clip.wav")
        source.write_bytes(data)
        try:
            wav = await extract_audio(source, out, max_seconds=MAX_CLIP_SECONDS)  # mono 16 kHz 16-bit WAV, the form the model takes
        except MediaProcessingFailed:
            raise ValidationFailed("The recording could not be read as audio.",
                                   details=[ErrorDetail(field="file", message="Unreadable audio.")]) from None
    duration_ms = max(0, len(wav) - 44) * 1000 // (16_000 * 2)
    try:
        async with guarded_ai_call(user_id, project, campaign.id):
            result = await capability.transcribe(wav, "audio/wav", language=language, duration_ms=duration_ms, stage="transcribing", agent="voice_director")
    except LLMError as exc:
        raise ctx.llm_failure(exc) from exc
    text = " ".join(" ".join(seg.text for seg in result.segments).split())
    message = result.status.message
    if len(text) > MAX_TRANSCRIPT_CHARS:
        text, message = text[:MAX_TRANSCRIPT_CHARS].rstrip(), f"The transcript was cut at {MAX_TRANSCRIPT_CHARS} characters, the length of an instruction."
    spoken = [seg.language for seg in result.segments if seg.language]
    return _transcript(
        result.status.status, text, message=message, language=max(set(spoken), key=spoken.count) if spoken else None,
        duration_ms=duration_ms, provider=result.status.provider, model_id=result.status.model_id,
    )


# --- planning ---------------------------------------------------------------------------------------------------------


async def _plan_context(s: AsyncSession, project: m.Project, campaign: m.Campaign, source: m.VersionNode) -> tuple[PlanContext, int]:
    """What the model is shown and the plan is validated against. Returns the context and the source version's number."""
    nodes = list((await s.execute(
        select(m.VersionNode).where(m.VersionNode.campaign_id == campaign.id).order_by(m.VersionNode.created_at, m.VersionNode.id)
    )).scalars())
    numbers = {n.id: i for i, n in enumerate(nodes, 1)}  # the Studio's numbering: v3 is the third node saved
    listed = [n for n in nodes if n.id != source.id and (n.parent_id is None or n in nodes[-LISTED_VERSIONS:])][-LISTED_VERSIONS:]
    refs = {f"V{numbers[n.id]}": VersionRef(n.id, numbers[n.id], n.label, list(n.elements)) for n in listed}
    proposed = (await s.execute(
        select(m.Chip).where(m.Chip.campaign_id == campaign.id, m.Chip.version_id == source.id, m.Chip.status == "proposed")
        .order_by(m.Chip.created_at, m.Chip.id).limit(LISTED_CHIPS)
    )).scalars()
    chip_refs = {f"K{i}": ChipRef(c.id, c.element_id, c.title, c.operation_type, c.change) for i, c in enumerate(proposed, 1)}
    region_rows = list((await s.execute(
        select(m.Region).where(m.Region.country_code == REGION_COUNTRY, m.Region.is_active).order_by(m.Region.name)
    )).scalars())
    by_region = await regions.languages_by_region(s, [r.id for r in region_rows])
    region_map = {r.code: (r.name, frozenset(lang.code for lang in by_region[r.id])) for r in region_rows}
    languages = {lang.code: lang.name for langs in by_region.values() for lang in langs}
    entries: dict[tuple[str, str], Mapping[str, Any]] = {}
    for language in {e.get("language") for e in source.elements}:
        for entry in await ctx.glossary_entries(s, project.id, language):
            entries[(entry["term"], entry["language"])] = entry
    brand = await brand_of(s, project.id)
    plan_ctx = PlanContext(
        version_id=source.id, elements={e["id"]: e for e in source.elements}, locked=await active_locks(s, campaign.id),
        versions=refs, chips=chip_refs, regions=region_map, languages=languages, base_region=source.region_code,
        glossary=list(entries.values()), protected=merge_terms(brand.protected_terms), prohibited=list(brand.prohibited_terms),
    )
    return plan_ctx, numbers[source.id]


def to_plan(row: m.VoicePlan) -> v.DirectPlan:
    steps = [v.DirectStep.model_validate(x) for x in row.steps]
    wanted = [x for x in steps if x.needs_confirmation and x.status != "blocked"]
    if not row.supported or not steps:
        status = "unsupported"
    elif not wanted:
        status = "refused" if any(x.status == "blocked" for x in steps) else "proposed"  # only blocked steps, or only openers
    elif all(x.status == "proposed" for x in wanted):
        status = "proposed"
    elif all(x.status == "applied" for x in wanted):
        status = "applied"
    elif any(x.status == "applied" for x in wanted) or any(x.status in ("proposed", "applying") for x in wanted):
        status = "partial"
    else:
        status = "refused"
    return v.DirectPlan(
        id=row.id, campaign_id=row.campaign_id, version_id=row.version_id, source=row.source,  # type: ignore[arg-type]
        instruction=row.instruction, transcript=row.transcript, mode=row.mode,  # type: ignore[arg-type]
        status=status, supported=row.supported, summary=row.summary, refusal=row.refusal,  # type: ignore[arg-type]
        supported_actions=list(v.SUPPORTED_ACTIONS), steps=steps, notes=list(row.notes), run_id=row.run_id,
        provider=row.provider, model_id=row.model_id, prompt_version=row.prompt_version,
        estimated_cost_usd=row.estimated_cost_usd, created_at=row.created_at, updated_at=row.updated_at,
    )


async def create_plan(user_id: UUID, campaign_id: UUID, body: v.DirectPlanRequest) -> v.DirectPlan:
    async with read_session() as s:
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        source = await node_in(s, campaign, body.version_id, "version_id") if body.version_id else await newest_node(s, campaign.id)
        if source is None:
            raise conflict("version_id", "This campaign has no version yet. Create one first (POST /campaigns/{id}/versions).")
        plan_ctx, number = await _plan_context(s, project, campaign, source)
        view = direct.model_view(plan_ctx, body.instruction, source.label, number)
    try:
        async with guarded_ai_call(user_id, project, campaign.id):  # 429 over the per-user or per-workspace limit
            result = await direct.propose_plan(ctx.gateway_for(project.mode), stage="planning", view=view)
    except LLMError as exc:
        raise ctx.llm_failure(exc) from exc
    out, trace = result.value, result.trace
    steps, notes = direct.validate_steps(out.steps, plan_ctx) if out.supported else ([], [])
    if trace.provider == "fixture":
        notes.append(DEMO_OUTPUT_NOTE)
    supported = out.supported and bool(steps)
    refusal = None
    if not supported:
        refusal = (out.refusal or "").strip() or "That could not be turned into steps with the tools available here."
    now = utcnow()
    run_id, plan_id = uuid4(), uuid4()
    async with session() as s, s.begin():
        campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
        await node_in(s, campaign, source.id, "version_id")  # still there
        s.add(m.AgentRun(
            id=run_id, project_id=project.id, campaign_id=campaign.id, run_type="voice_direct", status="completed", mode=project.mode,
            inputs={"plan_id": str(plan_id), "version_id": str(source.id), "source": body.source, "instruction_chars": len(body.instruction)},
            progress=RunProgress(stage="planning", completed_steps=1, total_steps=1, message="Plan ready.").model_dump(),
            result={"plan_id": str(plan_id), "supported": supported, "steps": len(steps)},
            result_ref=RunResultRef(resource="voice_plan", ids=[plan_id], url=f"{API}/campaigns/{campaign.id}/direct/plans/{plan_id}").model_dump(mode="json"),
            steps=[trace.model_dump(mode="json")], created_at=now, started_at=now, completed_at=now, created_by=user_id,
        ))
        await s.flush()
        row = m.VoicePlan(
            id=plan_id, project_id=project.id, campaign_id=campaign.id, version_id=source.id, run_id=run_id, mode=project.mode,
            source=body.source, instruction=body.instruction, transcript=body.transcript, supported=supported,
            summary=(out.summary or "").strip() or None, refusal=refusal, steps=[x.model_dump(mode="json") for x in steps], notes=notes,
            provider=trace.provider, model_id=trace.model_id, prompt_version=trace.prompt_version,
            estimated_cost_usd=trace.usage.estimated_cost_usd if trace.usage else None, created_by=user_id, created_at=now, updated_at=now,
        )
        s.add(row)
        await record_audit(s, action="studio.voice_plan", target_type="voice_plan", target_id=str(plan_id), workspace_id=project.workspace_id,
                           actor_user_id=user_id, detail={"campaign_id": str(campaign.id), "source": body.source, "steps": len(steps), "supported": supported})
    return to_plan(row)


async def list_plans(user_id: UUID, campaign_id: UUID, limit: int, offset: int) -> v.DirectPlanPage:
    async with read_session() as s:
        campaign, _ = await campaign_for(s, user_id, campaign_id)
        stmt = select(m.VoicePlan).where(m.VoicePlan.campaign_id == campaign.id)
        rows, total = await paginate(s, stmt.order_by(m.VoicePlan.created_at.desc(), m.VoicePlan.id), limit, offset)
    return v.DirectPlanPage(items=[to_plan(r) for r in rows], limit=limit, offset=offset, total=total)


async def _plan_row(s: AsyncSession, campaign: m.Campaign, plan_id: UUID) -> m.VoicePlan:
    row = await s.get(m.VoicePlan, plan_id)
    if row is None or row.campaign_id != campaign.id:
        raise not_found("Plan")
    return row


async def get_plan(user_id: UUID, campaign_id: UUID, plan_id: UUID) -> v.DirectPlan:
    async with read_session() as s:
        campaign, _ = await campaign_for(s, user_id, campaign_id)
        return to_plan(await _plan_row(s, campaign, plan_id))


# --- applying confirmed steps ----------------------------------------------------------------------------------------


def _step_error(field: str, message: str) -> ValidationFailed:
    return ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=field, message=message)])


async def _claim_steps(user_id: UUID, campaign_id: UUID, plan_id: UUID, step_ids: list[str]) -> tuple[v.DirectPlan, list[str]]:
    """Check the confirmation against the stored plan and mark the confirmed steps as being applied (so a double click, or
    a second tab, cannot apply them twice). Returns the plan and the confirmed ids in plan order."""
    wanted = list(dict.fromkeys(step_ids))
    async with session() as s, s.begin():
        campaign, _ = await campaign_for(s, user_id, campaign_id, writable=True)
        row = await _plan_row(s, campaign, plan_id)
        if not row.supported:
            raise conflict("plan_id", "This instruction could not be planned, so there is nothing to apply.")
        steps = [dict(x) for x in row.steps]
        by_id = {x["id"]: x for x in steps}
        stale = row.updated_at < datetime.now(UTC) - CLAIM_STALE
        for sid in wanted:
            step = by_id.get(sid)
            if step is None:
                raise _step_error("step_ids", f"This plan has no step {sid}.")
            if not step["needs_confirmation"]:
                raise _step_error("step_ids", f"{sid} only opens a workspace; there is nothing to confirm.")
            if step["status"] == "blocked":
                raise conflict("step_ids", f"{sid} was refused when the plan was made: {(step['blocked'] or {}).get('message', 'blocked')}")
            if step["status"] == "applied":
                raise conflict("step_ids", f"{sid} was already applied.")
            if step["status"] == "applying" and not stale:
                raise conflict("step_ids", f"{sid} is being applied by another request.")
        for sid in wanted:
            by_id[sid]["status"] = "applying"
        row.steps, row.updated_at = steps, utcnow()
        plan = to_plan(row)
    return plan, [x["id"] for x in steps if x["id"] in wanted]


async def _save_step(plan_id: UUID, step_id: str, status: str, result: v.DirectStepResult) -> None:
    async with session() as s, s.begin():
        row = await s.get(m.VoicePlan, plan_id)
        assert row is not None
        steps = [dict(x) for x in row.steps]
        for step in steps:
            if step["id"] == step_id:
                step["status"], step["result"] = status, result.model_dump(mode="json")
        row.steps, row.updated_at = steps, utcnow()


async def apply_plan(user_id: UUID, campaign_id: UUID, plan_id: UUID, body: v.DirectApply) -> v.DirectPlan:
    plan, ordered = await _claim_steps(user_id, campaign_id, plan_id, body.step_ids)
    by_id = {x.id: x for x in plan.steps}
    data_steps = sum(1 for x in plan.steps if x.changes_data and x.status != "blocked")
    share = plan.estimated_cost_usd / data_steps if plan.estimated_cost_usd is not None and data_steps else None
    current = plan.version_id
    for sid in ordered:
        step = by_id[sid]
        try:
            result = await _run_step(user_id, campaign_id, plan, step, current, share)
            status = "applied"
        except Conflict as exc:  # a refusal by the rules (a lock set since the plan was made): nothing changed
            status, result = "refused", v.DirectStepResult(message=exc.message)
        except AppError as exc:
            status, result = "failed", v.DirectStepResult(message=exc.message)
        await _save_step(plan_id, sid, status, result)
        if status == "applied" and result.version_id and step.kind != "propose_chips":
            current = result.version_id  # the next step starts from the version this one made
    return await get_plan(user_id, campaign_id, plan_id)


async def _run_step(
    user_id: UUID, campaign_id: UUID, plan: v.DirectPlan, step: v.DirectStep, current: UUID, share: float | None
) -> v.DirectStepResult:
    trail = {"direct_plan_id": str(plan.id), "direct_step_id": step.id, "direct_source": plan.source}
    reason = plan.instruction  # the person's own words are the reason on every version this makes
    if step.kind == "edit_element":
        async with session() as s, s.begin():
            campaign, project = await campaign_for(s, user_id, campaign_id, writable=True)
            source = await node_in(s, campaign, current, "version_id")
            op, node = await record_operation(
                s, project=project, campaign=campaign, source=source,
                spec=OpSpec("replace_text", edits=[Edit(step.element_id or "", {"value": step.after})]), actor="ai", actor_user_id=user_id,
                reason=reason, claim_ids=[], params={**trail, "element_id": step.element_id, "rationale": step.rationale},
                label=f"Direct: {step.title}"[:80], prompt_version=plan.prompt_version, estimated_cost_usd=share,
            )
        raise_if_rejected(op)  # after the commit: a refused operation stays on record, like every other refusal
        assert node is not None
        return v.DirectStepResult(message="Changed. This is a new version; the previous one is untouched.", version_id=node.id, operation_id=op.id)
    if step.kind == "apply_chip":
        applied = await chips.apply_chip(user_id, campaign_id, step.chip_id or UUID(int=0), vs.ChipApply(version_id=current),
                                         reason=reason, extra_params=trail)
        return v.DirectStepResult(message="Chip applied as a new version.", version_id=applied.version.id, operation_id=applied.operation.id)
    if step.kind == "propose_chips":
        made = await chips.generate_chips(user_id, campaign_id, vs.ChipGenerate(
            version_id=current, element_id=step.element_id or "", region_code=step.region_code or "", max_chips=4))
        dropped = f" {made.dropped} proposal(s) were dropped by code checks." if made.dropped else ""
        message = (f"{len(made.chips)} chip(s) proposed. Nothing has changed yet: review them in Elements, or ask to apply one.{dropped}"
                   if made.chips else f"No chip survived the code checks, so nothing was proposed.{dropped}")
        return v.DirectStepResult(message=message, chip_ids=[c.id for c in made.chips], chip_version_id=current if made.chips else None)
    if step.kind in ("lock_element", "unlock_element"):
        lock_reason = f"Direct: {plan.instruction}"[:300]
        if step.kind == "lock_element":
            await versions.set_lock(user_id, campaign_id, step.element_id or "", vs.LockCreate(reason=lock_reason))
            return v.DirectStepResult(message="Locked. A lock holds in every version, so no new version was made.")
        await versions.unset_lock(user_id, campaign_id, step.element_id or "")
        return v.DirectStepResult(message="Unlocked. A lock holds in every version, so no new version was made.")
    if step.kind == "restore_version":
        restored = await versions.restore_version(user_id, campaign_id, step.version_id or UUID(int=0), vs.RestoreRequest(
            onto_version_id=current, reason=reason))
        return v.DirectStepResult(message="Restored as a new version.", version_id=restored.version.id, operation_id=restored.operation.id)
    assert step.kind == "transcreate"
    accepted = await transcreate.start_transcreate(user_id, campaign_id, vs.TranscreateRequest(
        version_id=current, region_code=step.region_code or "", language=step.language or "", element_ids=step.element_ids or None,
    ), direct={**trail, "instruction": plan.instruction})
    return v.DirectStepResult(message="Transcreation started. Its version appears when the run finishes.", run_id=accepted.run_id)
