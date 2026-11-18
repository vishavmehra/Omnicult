"""Message Check service (lab-t3): start a check of the intended message in each target region, store each participant's restatement
and the comparison's marks, and read the run back with scores, verdicts and rates computed by code.

A run is an `audience_runs` row of kind `message_check`. Its panel is sampled region by region by the same sampler as every panel
and stored as ordinary panel participants; a participant's `response` holds what the model wrote (restatement, recall) and what
the comparison marked. Scores, verdicts and every rate are derived from those marks at read time (`analytics.message_check`), so
the rules in force are named in the result and a rule change never rewrites a stored mark.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import message_check as stats
from app.core.config import get_settings
from app.db import models as m
from app.db.session import read_session
from app.llm.gateway import LLMGateway
from app.schemas import audience as av
from app.schemas import lab_message_check as v
from app.schemas.audience import RegionRef
from app.schemas.campaigns import CampaignContent
from app.services import audience, lab_t3
from app.workflows.audience_types import PanelMember
from app.workflows.lab_t3_types import CheckTarget, MessageCheckInput
from app.workflows.message_check import STAGES, run_message_check
from app.workflows.types import BrandContext, WorkflowContext


async def start_message_check(user_id: UUID, campaign_id: UUID, body: v.MessageCheckCreate) -> av.AudienceRunAccepted:
    settings = get_settings()
    states = [t.region_code for t in body.targets]
    unknown = [c for c in states if c not in audience.REGION_NAME]
    if unknown:
        raise audience._invalid("targets", f"Unknown state or union territory code(s): {', '.join(unknown)}.")
    if len(states) > settings.lab_t3_message_check_max_regions:
        raise audience._invalid("targets", f"Check at most {settings.lab_t3_message_check_max_regions} regions at once on this server.")
    if body.sampling.states and set(body.sampling.states) != set(states):
        raise audience._invalid("sampling.states", "States come from the targets: omit them here, or list exactly the target regions.")
    cap = settings.lab_t3_message_check_max_per_region
    if body.size_per_region < lab_t3.MIN_PER_REGION or body.size_per_region > cap:
        raise audience._invalid("size_per_region", f"Use {lab_t3.MIN_PER_REGION} to {cap} participants per region on this server.")
    async with read_session() as s:
        campaign, project = await audience._campaign_for_run(s, user_id, campaign_id)
        message, message_source = (body.intended_message, "request") if body.intended_message else (None, "brief")
        if message is None:
            message = await lab_t3.brief_primary_message(s, campaign.id)
        if not message:
            raise audience._invalid("intended_message", "State the message to check, or add a primary message to the campaign brief.")
        targets = []
        for t in body.targets:
            creative, version_id = await lab_t3.resolve_creative(s, user_id, campaign, t.content_version_id, t.creative)
            targets.append({"region_code": t.region_code, "region_name": audience.REGION_NAME[t.region_code], "creative": creative,
                            "version_ref": t.version_ref, "content_version_id": str(version_id) if version_id else None})
        brand = await audience._brand_of(s, project.id)
    points = body.key_points or stats.split_key_points(message)
    if not points:
        raise audience._invalid("key_points", "Give at least one key point.")
    people, dims = lab_t3.sample_by_state(
        size=body.size_per_region * len(states), states=states, languages=body.sampling.languages, city_tiers=body.sampling.city_tiers,
        age_bands=body.sampling.age_bands, seed=body.seed, weights=body.sampling.weights)
    run_id = uuid4()
    inputs = {
        "intended_message": message, "intended_message_source": message_source,
        "key_points": [{"id": f"K{n}", "text": p} for n, p in enumerate(points, 1)],
        "key_points_source": "request" if body.key_points else "split_by_code", "targets": targets, "brand": audience._brand_snapshot(brand),
        "panel": audience._panel_inputs(len(people), dims, people, body.seed),
    }
    return await audience._create_run(
        user_id, project, campaign, "message_check", run_id=run_id, config=body.model_dump(mode="json"), inputs=inputs,
        region_codes=list(states), content_version_id=None, version_ref=None, seed=body.seed, participants=audience._panel_rows(run_id, people))


async def _build_input(s: AsyncSession, run: m.AudienceRun) -> MessageCheckInput:
    i = run.inputs
    rows = await audience._participants(s, run.id)
    members = [PanelMember(id=r.id, ordinal=r.ordinal, state_code=r.state_code, state_name=r.state_name, language=r.language,
                           language_name=r.language_name, city_tier=r.city_tier, age_band=r.age_band, traits=r.traits, persona=r.persona)
               for r in rows]
    return MessageCheckInput(
        context=WorkflowContext(run_id=run.id, project_id=run.project_id, campaign_id=run.campaign_id, mode=run.mode,
                                brand=BrandContext.model_validate(i["brand"])),
        intended_message=i["intended_message"], key_points={k["id"]: k["text"] for k in i["key_points"]},
        targets=[CheckTarget(region_code=t["region_code"], region_name=t["region_name"], creative=CampaignContent.model_validate(t["creative"]),
                             version_ref=t["version_ref"]) for t in i["targets"]],
        participants=members, seed=run.seed or 0)


async def _run(inp: MessageCheckInput, llm: LLMGateway, progress: Any) -> Any:
    return await run_message_check(inp, llm, progress)


async def _persist(s: AsyncSession, run: m.AudienceRun, outcome: Any, now: datetime) -> None:
    """What the model wrote and what the comparison marked, on each participant. A participant is `compared` only when every key
    point was marked; the rest stay out of every rate."""
    ids = [k["id"] for k in run.inputs["key_points"]]
    for row in await audience._participants(s, run.id):
        reading = outcome.readings.get(row.id)
        if reading is None:
            continue
        judged = outcome.judgements.get(row.id)
        row.response = {
            "restated": reading.restated, "restated_en": reading.restated_en, "recall": reading.recall, "compared": judged is not None,
            "points": [{"point_id": k, "restated": judged.coverage[k], "recalled": judged.recalled[k]} for k in ids] if judged else [],
            "misreading": {"label": judged.misreading[0], "why": judged.misreading[1]} if judged and judged.misreading else None}
    run.result = {"rules_version": stats.RULES_VERSION}


def _checked(row: m.PanelParticipant) -> stats.Checked:
    r = row.response or {}
    done = bool(r.get("compared"))
    return stats.Checked(
        id=row.id, ordinal=row.ordinal, state_code=row.state_code, language=row.language, language_name=row.language_name, completed=done,
        restated=r.get("restated", ""), restated_en=r.get("restated_en", ""), coverage={p["point_id"]: p["restated"] for p in r.get("points", [])},
        recalled={p["point_id"]: p["recalled"] for p in r.get("points", [])}, misreading=(r.get("misreading") or {}).get("label"))


def _participant_view(row: m.PanelParticipant, checked: stats.Checked, ids: list[str], message: str) -> v.MessageCheckParticipant:
    r = row.response
    response = None
    if r:
        misreading = r.get("misreading")
        response = v.MessageCheckResponse(
            restated=r["restated"], restated_en=r["restated_en"], recall=list(r["recall"]),
            points=[v.MessageCheckPointJudgement(point_id=p["point_id"], restated=p["restated"], recalled=p["recalled"]) for p in r["points"]],
            misreading=v.MessageCheckMisreading(**misreading) if misreading else None, score=checked.score(ids), verdict=checked.verdict(ids),
            wording_overlap=stats.overlap_with(message, r["restated_en"]))
    return v.MessageCheckParticipant(**audience._participant_base(row), response=response)


async def _result(s: AsyncSession, run: m.AudienceRun) -> v.MessageCheckResult:
    i = run.inputs
    rows = await audience._participants(s, run.id)
    points = [(k["id"], k["text"]) for k in i["key_points"]]
    ids = [p for p, _ in points]
    people = [_checked(r) for r in rows]
    summary = None
    if run.status in audience.USABLE and any(p.completed for p in people):
        summary = stats.summarise(points, people, [
            (RegionRef(code=t["region_code"], name=t["region_name"]), audience._copy(t["creative"]), t["version_ref"]) for t in i["targets"]])
    return v.MessageCheckResult(
        id=run.id, campaign_id=run.campaign_id, project_id=run.project_id, status=run.status,  # type: ignore[arg-type]
        mode=run.mode, intended_message=i["intended_message"], intended_message_source=i["intended_message_source"],
        key_points=[v.MessageCheckPoint(id=k, text=t) for k, t in points], key_points_source=i["key_points_source"],
        panel=audience._panel_description(run),
        participants=[_participant_view(r, c, ids, i["intended_message"]) for r, c in zip(rows, people)], summary=summary,
        disclosure=av.PanelDisclosure(), limitations=list(run.limitations), error=audience._error(run), progress=audience._progress(run),
        run_metadata=audience._metadata(run), created_at=run.created_at)


async def get_check(user_id: UUID, campaign_id: UUID, run_id: UUID) -> v.MessageCheckResult:
    return await audience.get_result(user_id, campaign_id, run_id, "message_check")


audience.register_kind("message_check", audience.KindHooks(
    url_path="message-checks", stages=STAGES, build_input=_build_input, run=_run, persist=_persist, result=_result))
