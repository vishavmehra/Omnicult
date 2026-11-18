"""Live Focus Group service (lab-t3): start a moderated session on an existing panel, save its transcript turn by turn, relay a
person's interjection, and read the session back with themes, splits and position changes counted by code.

A session is an `audience_runs` row of kind `focus_group`. Its speakers are participants of a finished Quick Read or Audience
Study (`inputs.panel`), voiced from what they said there. Turns are written to `audience_focus_turns` as the workflow produces
them, so a client that polls the result sees the transcript grow while the run stages move. A question typed while the session
runs is stored as an interjection and relayed at the next turn boundary; once the session reaches its last stage it is refused.
"""

import asyncio
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import focus_group as stats
from app.core.config import get_settings
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.llm.gateway import LLMGateway
from app.schemas import audience as av
from app.schemas import lab_focus_group as v
from app.schemas.audience import GroundingClaim, RegionRef
from app.schemas.campaigns import CampaignContent
from app.services import audience, lab_t3
from app.services.audit import record_audit
from app.services.common import conflict, require_writable
from app.workflows.focus_group import STAGES, run_focus_group
from app.workflows.lab_t3_types import DraftTurn, FocusGroupInput, FocusSpeaker
from app.workflows.types import BrandContext, WorkflowContext

PANEL_KINDS = ("quick_read", "audience_study")
LATE = ("analysing_themes",)  # the stage after which a question can no longer be relayed
SPENT = "This session has finished, so it cannot relay a question. Start a new session, or use Ask the Panel to question the panel further."


def _first_reaction(row: m.PanelParticipant, kind: str) -> tuple[str | None, str | None]:
    r = row.response or {}
    if kind == "quick_read":
        return r.get("first_reaction"), (r.get("message") or {}).get("restated")
    answers = r.get("answers") or []
    return (answers[0]["answer"] if answers else None), None


async def start_focus_group(user_id: UUID, campaign_id: UUID, body: v.FocusGroupCreate) -> av.AudienceRunAccepted:
    settings = get_settings()
    guide = [q.strip() for q in (body.guide or stats.DEFAULT_GUIDE[: stats.DEFAULT_GUIDE_SIZE]) if q.strip()]
    if not guide or len(guide) > settings.lab_t3_focus_max_guide_questions:
        raise audience._invalid("guide", f"Use 1 to {settings.lab_t3_focus_max_guide_questions} questions.")
    async with read_session() as s:
        campaign, project = await audience._campaign_for_run(s, user_id, campaign_id)
        panel, _ = await audience._run_in(s, user_id, campaign_id, body.panel_run_id, PANEL_KINDS)
        if panel.status not in audience.USABLE:
            raise conflict("panel_run_id", f"The panel has no usable responses yet (status: {panel.status}).")
        rows = await audience._participants(s, panel.id)
    usable = [r for r in rows if r.response is not None and (panel.kind == "quick_read" or r.response.get("status") == "completed")]
    if len(usable) < lab_t3.MIN_FOCUS_SPEAKERS:
        raise conflict("panel_run_id", "The panel needs at least two participants with a stored response to hold a discussion.")
    if body.participant_ids:
        wanted = list(dict.fromkeys(body.participant_ids))
        if len(wanted) > settings.lab_t3_focus_max_speakers:
            raise audience._invalid("participant_ids", f"A session can seat at most {settings.lab_t3_focus_max_speakers} speakers.")
        by_id = {r.id: r for r in usable}
        unknown = [w for w in wanted if w not in by_id]
        if unknown:
            raise audience._invalid("participant_ids", "Every speaker must be a participant of that panel with a stored response.")
        chosen = [by_id[w] for w in wanted]
        chosen.sort(key=lambda r: r.ordinal)
    else:
        chosen = stats.pick_speakers(usable, min(body.speakers, settings.lab_t3_focus_max_speakers, len(usable)), body.seed)
    speakers = []
    for r in chosen:
        reaction, restated = _first_reaction(r, panel.kind)
        speakers.append(FocusSpeaker(
            id=r.id, ordinal=r.ordinal, state_code=r.state_code, state_name=r.state_name, language=r.language, language_name=r.language_name,
            city_tier=r.city_tier, age_band=r.age_band, traits=r.traits, persona=r.persona, stance=audience._stance_of(r, panel.kind),
            first_reaction=reaction, restated=restated))
    states = list(dict.fromkeys(sp.state_code for sp in speakers))
    claims = [c for c in panel.inputs["claims"] if c.get("region_code") in (None, *states)]
    inputs = {
        "panel": {"run_id": str(panel.id), "kind": panel.kind, "version_ref": panel.version_ref},
        "regions": [{"code": c, "name": audience.REGION_NAME.get(c, c)} for c in states], "creative": panel.inputs["creative"],
        "intended_message": panel.inputs.get("intended_message"), "claims": claims,
        "evidence_strength": {k: val for k, val in panel.inputs.get("evidence_strength", {}).items() if k in states},
        "brand": panel.inputs["brand"], "guide": guide, "speakers": [sp.model_dump(mode="json") for sp in speakers],
        "max_interjections": settings.lab_t3_focus_max_interjections,
    }
    return await audience._create_run(
        user_id, project, campaign, "focus_group", run_id=uuid4(), config=body.model_dump(mode="json"), inputs=inputs, region_codes=states,
        content_version_id=None, version_ref=panel.version_ref, seed=body.seed)


async def interject(user_id: UUID, campaign_id: UUID, run_id: UUID, body: v.FocusGroupInterjectionCreate) -> v.FocusGroupInterjectionView:
    """Queue a question for the moderator to relay at the next turn boundary. Refused once the session has finished."""
    text = body.text.strip()
    if not text:
        raise audience._invalid("text", "Write a question.")
    limit = get_settings().lab_t3_focus_max_interjections
    async with session() as s, s.begin():
        run, project = await audience._run_in(s, user_id, campaign_id, run_id, ("focus_group",))
        require_writable(project)
        if run.status not in audience.ACTIVE or (run.progress or {}).get("stage") in LATE:
            raise conflict("run_id", SPENT)
        used = len((await s.execute(select(m.FocusGroupInterjection.id).where(m.FocusGroupInterjection.run_id == run.id))).all())
        if used >= limit:
            raise conflict("text", f"A session relays at most {limit} questions.")
        row = m.FocusGroupInterjection(id=uuid4(), run_id=run.id, text=text, status="pending", created_by=user_id, created_at=utcnow())
        s.add(row)
        await record_audit(s, action="audience.focus_group.interject", target_type="audience_run", target_id=str(run.id),
                           workspace_id=run.workspace_id, actor_user_id=user_id, detail={"length": len(text)})
        await s.flush()
        return _interjection_view(row)


def _interjection_view(row: m.FocusGroupInterjection) -> v.FocusGroupInterjectionView:
    return v.FocusGroupInterjectionView(id=row.id, run_id=row.run_id, text=row.text, status=row.status, created_at=row.created_at,  # type: ignore[arg-type]
                                        taken_at=row.taken_at)


# --- executing: the workflow's callbacks ----------------------------------------------------------------------------------


class _IO:
    """Saves each turn as it is written and hands over what people typed. Demo sessions pace the replay of their fixtures so the
    transcript streams the way a live one does (the pause is a setting, 0 in tests)."""

    def __init__(self, run_id: UUID, demo: bool) -> None:
        self.run_id = run_id
        self.pause = get_settings().lab_t3_demo_turn_delay_seconds if demo and not lab_t3.replay_is_instant() else 0.0

    async def save_turn(self, t: DraftTurn) -> None:
        async with session() as s, s.begin():
            s.add(m.FocusGroupTurn(
                id=uuid4(), run_id=self.run_id, turn_index=t.index, round_index=t.round_index, kind=t.kind, participant_id=t.participant_id,
                text=t.text, reply_to_turn_index=t.reply_to, relation=t.relation, stance=t.stance, themes=list(t.themes),
                claim_ids=[str(c) for c in t.claim_ids], interjection_id=t.interjection_id, created_at=utcnow()))
        if self.pause:
            await asyncio.sleep(self.pause)

    async def take_interjections(self, limit: int) -> list[tuple[UUID, str]]:
        async with session() as s, s.begin():
            rows = (await s.execute(select(m.FocusGroupInterjection).where(
                m.FocusGroupInterjection.run_id == self.run_id, m.FocusGroupInterjection.status == "pending")
                .order_by(m.FocusGroupInterjection.created_at, m.FocusGroupInterjection.id).limit(limit))).scalars().all()
            now = utcnow()
            for r in rows:
                r.status, r.taken_at = "taken", now
            return [(r.id, r.text) for r in rows]


async def _build_input(s: AsyncSession, run: m.AudienceRun) -> FocusGroupInput:
    i = run.inputs
    return FocusGroupInput(
        context=WorkflowContext(run_id=run.id, project_id=run.project_id, campaign_id=run.campaign_id, mode=run.mode,
                                brand=BrandContext.model_validate(i["brand"])),
        creative=CampaignContent.model_validate(i["creative"]), intended_message=i.get("intended_message"),
        speakers=[FocusSpeaker.model_validate(x) for x in i["speakers"]], guide=list(i["guide"]),
        claims=[GroundingClaim.model_validate(c) for c in i["claims"]], max_interjections=i["max_interjections"], seed=run.seed or 0)


async def _run(inp: FocusGroupInput, llm: LLMGateway, progress: Any) -> Any:
    return await run_focus_group(inp, llm, _IO(inp.context.run_id, inp.context.mode == "demo"), progress)


async def _persist(s: AsyncSession, run: m.AudienceRun, outcome: Any, now: datetime) -> None:
    """The turns are already saved. A question that arrived too late to be relayed is marked dropped, so the record is honest."""
    await s.execute(update(m.FocusGroupInterjection).where(
        m.FocusGroupInterjection.run_id == run.id, m.FocusGroupInterjection.status == "pending").values(status="dropped"))
    run.result = {"turns": len(outcome.turns)}


# --- reading ----------------------------------------------------------------------------------------------------------------


def _recs(rows: list[m.FocusGroupTurn], ordinals: dict[UUID, int]) -> list[stats.TurnRec]:
    return [stats.TurnRec(index=t.turn_index, round_index=t.round_index, kind=t.kind, participant_id=t.participant_id,
                          ordinal=ordinals.get(t.participant_id) if t.participant_id else None, text=t.text, reply_to=t.reply_to_turn_index,
                          relation=t.relation, stance=t.stance, themes=tuple(t.themes)) for t in rows]


async def _result(s: AsyncSession, run: m.AudienceRun) -> v.FocusGroupResult:
    i = run.inputs
    turns = list((await s.execute(select(m.FocusGroupTurn).where(m.FocusGroupTurn.run_id == run.id)
                                  .order_by(m.FocusGroupTurn.turn_index))).scalars())
    inter = list((await s.execute(select(m.FocusGroupInterjection).where(m.FocusGroupInterjection.run_id == run.id)
                                  .order_by(m.FocusGroupInterjection.created_at, m.FocusGroupInterjection.id))).scalars())
    speakers = [FocusSpeaker.model_validate(x) for x in i["speakers"]]
    ordinals = {sp.id: sp.ordinal for sp in speakers}
    claims = [GroundingClaim.model_validate(c) for c in i["claims"]]
    strong = {c.id for c in claims if c.kind in ("observed", "calculated")}
    cited = list(dict.fromkeys(UUID(c) for t in turns for c in t.claim_ids))
    views = []
    for t in turns:
        ids = [UUID(c) for c in t.claim_ids]
        views.append(v.FocusGroupTurnView(
            id=t.id, turn_index=t.turn_index, round_index=t.round_index, kind=t.kind, participant_id=t.participant_id,  # type: ignore[arg-type]
            ordinal=ordinals.get(t.participant_id) if t.participant_id else None, text=t.text, reply_to_turn_index=t.reply_to_turn_index,
            relation=t.relation, stance=t.stance, themes=list(t.themes), claim_ids=ids,  # type: ignore[arg-type]
            basis=None if t.kind != "participant" else ("claim_supported" if strong & set(ids) else "interpretation"),
            interjection_id=t.interjection_id, created_at=t.created_at))
    spoken = [t for t in views if t.kind == "participant"]
    limitations = list(run.limitations)
    if run.status == "failed" and turns:
        limitations.append("The session stopped early. The transcript up to that point was kept.")
    stage = (run.progress or {}).get("stage")
    return v.FocusGroupResult(
        id=run.id, campaign_id=run.campaign_id, project_id=run.project_id, status=run.status,  # type: ignore[arg-type]
        mode=run.mode, panel_run_id=UUID(i["panel"]["run_id"]), panel_kind=i["panel"]["kind"],  # type: ignore[arg-type]
        regions=[RegionRef.model_validate(r) for r in i["regions"]], creative=audience._copy(i["creative"]),
        intended_message=i.get("intended_message"), guide=list(i["guide"]),
        speakers=[v.FocusGroupSpeaker(
            id=sp.id, ordinal=sp.ordinal, state_code=sp.state_code, state_name=sp.state_name, language=sp.language,
            language_name=sp.language_name, city_tier=sp.city_tier, age_band=sp.age_band, persona=sp.persona, traits=sp.traits,  # type: ignore[arg-type]
            stored_stance=sp.stance, stored_reaction=sp.first_reaction) for sp in speakers],  # type: ignore[arg-type]
        turns=views, interjections=[_interjection_view(r) for r in inter],
        interjections_open=run.status in audience.ACTIVE and stage not in LATE,
        summary=stats.summarise(_recs(turns, ordinals), i["guide"]),
        grounding=av.GroundingSummary(
            region_codes=list(run.region_codes), claims_supplied=len(claims), claims=claims, evidence_strength=i.get("evidence_strength", {}),
            cited_claim_ids=cited, claim_supported_statements=sum(1 for t in spoken if t.basis == "claim_supported"),
            interpretation_statements=sum(1 for t in spoken if t.basis == "interpretation"), note=audience.GROUNDING_NOTE),
        disclosure=av.PanelDisclosure(), limitations=limitations, error=audience._error(run), progress=audience._progress(run),
        run_metadata=audience._metadata(run), created_at=run.created_at)


async def get_session(user_id: UUID, campaign_id: UUID, run_id: UUID) -> v.FocusGroupResult:
    return await audience.get_result(user_id, campaign_id, run_id, "focus_group")


audience.register_kind("focus_group", audience.KindHooks(
    url_path="focus-groups", stages=STAGES, build_input=_build_input, run=_run, persist=_persist, result=_result))

