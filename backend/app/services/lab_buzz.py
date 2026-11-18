"""Buzz Simulator service (lab-t3): start a simulation on a freshly sampled synthetic population, save each round's acts as they
are written, and read the run back with reach, sentiment, cohorts and message change counted by code.

A run is an `audience_runs` row of kind `buzz_sim`. Its population is sampled by the same sampler as every panel (state, language,
city tier and age band only), state by state so each account reads a language of its own state, and stored as ordinary panel
participants. The acts are rows of `audience_buzz_acts`. Nothing is read from a social platform and nothing here forecasts reach.
"""

import asyncio
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import buzz as stats
from app.core.config import get_settings
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.llm.gateway import LLMGateway
from app.schemas import audience as av
from app.schemas import lab_buzz as v
from app.schemas.audience import RegionRef
from app.schemas.campaigns import CampaignContent
from app.services import audience, lab_t3
from app.workflows.audience_types import PanelMember
from app.workflows.buzz import STAGES, reference_message, run_buzz
from app.workflows.lab_t3_types import BuzzInput, DraftAct
from app.workflows.types import BrandContext, WorkflowContext


async def start_buzz(user_id: UUID, campaign_id: UUID, body: v.BuzzCreate) -> av.AudienceRunAccepted:
    settings = get_settings()
    states = body.sampling.states or []
    if not states:
        raise audience._invalid("sampling.states", "Name at least one state or union territory to simulate.")
    unknown = [c for c in states if c not in audience.REGION_NAME]
    if unknown:
        raise audience._invalid("sampling.states", f"Unknown state or union territory code(s): {', '.join(unknown)}.")
    if body.size < lab_t3.MIN_BUZZ or body.size > settings.lab_t3_buzz_max_participants:
        raise audience._invalid("size", f"Use {lab_t3.MIN_BUZZ} to {settings.lab_t3_buzz_max_participants} simulated accounts on this server.")
    if body.size < len(states) * 3:
        raise audience._invalid("size", "Give each state at least three accounts.")
    if body.rounds > settings.lab_t3_buzz_max_rounds:
        raise audience._invalid("rounds", f"Use at most {settings.lab_t3_buzz_max_rounds} rounds on this server.")
    async with read_session() as s:
        campaign, project = await audience._campaign_for_run(s, user_id, campaign_id)
        creative, version_id = await lab_t3.resolve_creative(s, user_id, campaign, body.content_version_id, body.creative)
        brand = await audience._brand_of(s, project.id)
    people, dims = lab_t3.sample_by_state(
        size=body.size, states=states, languages=body.sampling.languages, city_tiers=body.sampling.city_tiers,
        age_bands=body.sampling.age_bands, seed=body.seed, weights=body.sampling.weights)
    run_id = uuid4()
    inputs = {
        "regions": [{"code": c, "name": audience.REGION_NAME[c]} for c in states], "creative": creative,
        "intended_message": body.intended_message, "brand": audience._brand_snapshot(brand), "platform": body.platform,
        "rounds": body.rounds, "initial_exposure": body.initial_exposure, "degree": body.degree,
        "panel": audience._panel_inputs(body.size, dims, people, body.seed),
    }
    return await audience._create_run(
        user_id, project, campaign, "buzz_sim", run_id=run_id, config=body.model_dump(mode="json"), inputs=inputs, region_codes=list(states),
        content_version_id=version_id, version_ref=body.version_ref, seed=body.seed, participants=audience._panel_rows(run_id, people))


class _IO:
    def __init__(self, run_id: UUID, demo: bool) -> None:
        self.run_id = run_id
        self.pause = get_settings().lab_t3_demo_turn_delay_seconds * 3 if demo and not lab_t3.replay_is_instant() else 0.0

    async def save_acts(self, acts: list[DraftAct]) -> None:
        async with session() as s, s.begin():
            s.add_all(m.BuzzAct(
                id=a.id, run_id=self.run_id, round_index=a.round_index, participant_id=a.participant_id, action=a.action, text=a.text,
                text_en=a.text_en, message_gloss=a.message_gloss, stance=a.stance, topics=list(a.topics), parent_act_id=a.parent_act_id,
                exposed_by=a.exposed_by, wording_overlap=a.wording_overlap, created_at=utcnow()) for a in acts)
        if self.pause:
            await asyncio.sleep(self.pause)


async def _build_input(s: AsyncSession, run: m.AudienceRun) -> BuzzInput:
    i = run.inputs
    rows = await audience._participants(s, run.id)
    members = [PanelMember(id=r.id, ordinal=r.ordinal, state_code=r.state_code, state_name=r.state_name, language=r.language,
                           language_name=r.language_name, city_tier=r.city_tier, age_band=r.age_band, traits=r.traits, persona=r.persona)
               for r in rows]
    return BuzzInput(
        context=WorkflowContext(run_id=run.id, project_id=run.project_id, campaign_id=run.campaign_id, mode=run.mode,
                                brand=BrandContext.model_validate(i["brand"])),
        creative=CampaignContent.model_validate(i["creative"]), intended_message=i.get("intended_message"), participants=members,
        platform=i["platform"], rounds=i["rounds"], initial_exposure=i["initial_exposure"], degree=i["degree"], seed=run.seed or 0)


async def _run(inp: BuzzInput, llm: LLMGateway, progress: Any) -> Any:
    return await run_buzz(inp, llm, _IO(inp.context.run_id, inp.context.mode == "demo"), progress)


async def _persist(s: AsyncSession, run: m.AudienceRun, outcome: Any, now: datetime) -> None:
    run.result = {"network": outcome.network, "seed_exposed": outcome.seed_exposed, "exposed_by": outcome.exposed_by,
                  "rounds_run": outcome.rounds_run, "ended": outcome.ended}


def _uuid(value: str | None) -> UUID | None:
    return UUID(value) if value else None


async def _result(s: AsyncSession, run: m.AudienceRun) -> v.BuzzResult:
    i, stored = run.inputs, run.result or {}
    rows = await audience._participants(s, run.id)
    by_id = {r.id: r for r in rows}
    acts = list((await s.execute(select(m.BuzzAct).where(m.BuzzAct.run_id == run.id)
                                 .order_by(m.BuzzAct.round_index, m.BuzzAct.created_at, m.BuzzAct.id))).scalars())
    reference, source = reference_message(CampaignContent.model_validate(i["creative"]), i.get("intended_message"))
    recs = [stats.ActRec(id=a.id, round_index=a.round_index, participant_id=a.participant_id, action=a.action, stance=a.stance,
                         topics=tuple(a.topics), parent_act_id=a.parent_act_id, exposed_by=a.exposed_by, gloss=a.message_gloss,
                         overlap=a.wording_overlap) for a in acts]
    done = run.status in audience.USABLE and bool(acts)
    exposed_by = {UUID(k): _uuid(val) for k, val in stored["exposed_by"].items()} if "exposed_by" in stored else None
    summary = stats.summarise(
        rows, recs, exposed_by=exposed_by, rounds_run=stored.get("rounds_run", max((a.round_index for a in acts), default=0)),
        ended=stored.get("ended", "stopped_early"), reference=reference, reference_source=source,
        network_method=stats.network_method(i["degree"])) if done else None
    views = []
    for a in acts:
        p = by_id[a.participant_id]
        views.append(v.BuzzActView(
            id=a.id, round_index=a.round_index, participant_id=a.participant_id, ordinal=p.ordinal, state_code=p.state_code,
            language=p.language, language_name=p.language_name, action=a.action, text=a.text, text_en=a.text_en,  # type: ignore[arg-type]
            message_gloss=a.message_gloss, stance=a.stance, topics=list(a.topics), parent_act_id=a.parent_act_id,  # type: ignore[arg-type]
            exposed_by_participant_id=a.exposed_by, wording_overlap=a.wording_overlap,
            changed_message=None if a.wording_overlap is None else a.wording_overlap < stats.MUTATION_THRESHOLD))
    return v.BuzzResult(
        id=run.id, campaign_id=run.campaign_id, project_id=run.project_id, status=run.status,  # type: ignore[arg-type]
        mode=run.mode, platform=i["platform"], regions=[RegionRef.model_validate(r) for r in i["regions"]],  # type: ignore[arg-type]
        creative=audience._copy(i["creative"]), intended_message=i.get("intended_message"), initial_exposure=i["initial_exposure"],
        degree=i["degree"], rounds_requested=i["rounds"], panel=audience._panel_description(run),
        participants=[av.PanelParticipant(**audience._participant_base(r)) for r in rows], acts=views, summary=summary,
        disclosure=av.PanelDisclosure(), limitations=list(run.limitations), error=audience._error(run), progress=audience._progress(run),
        run_metadata=audience._metadata(run), created_at=run.created_at)


async def get_simulation(user_id: UUID, campaign_id: UUID, run_id: UUID) -> v.BuzzResult:
    return await audience.get_result(user_id, campaign_id, run_id, "buzz_sim")


audience.register_kind("buzz_sim", audience.KindHooks(
    url_path="buzz-simulations", stages=STAGES, build_input=_build_input, run=_run, persist=_persist, result=_result))
