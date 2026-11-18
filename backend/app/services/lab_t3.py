"""Shared parts of the Audience Lab sessions (lab-t3): Live Focus Group, Buzz Simulator and Message Check.

The three kinds are `audience_runs` like Quick Read. They start, run, fail and read through `services.audience` (the
`KindHooks` seam registered at the bottom of each feature module) and reuse its panel sampling, participants, idempotency,
usage scope and access rules. This module holds what they share: the form defaults, the limits, creative and brief lookups,
a per-state panel sampler, and the demo hook that fills a demo project with one finished session of each kind.
"""

import asyncio
from collections.abc import Sequence
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.focus_group import DEFAULT_GUIDE, DEFAULT_GUIDE_SIZE
from app.analytics.message_check import MAX_KEY_POINTS, split_key_points
from app.analytics.panel import AGE_BANDS, CITY_TIERS, SampledParticipant, sample_panel
from app.analytics.population import allocate
from app.core.config import get_settings
from app.db import models as m
from app.db.session import read_session
from app.schemas import lab_sessions as v
from app.schemas.campaigns import CampaignContent
from app.services import audience
from app.services.common import get_owned

PLATFORMS = (("instagram", "Instagram"), ("facebook", "Facebook"), ("youtube", "YouTube"), ("x", "X"), ("whatsapp", "WhatsApp"))
MIN_FOCUS_SPEAKERS = 2
MIN_BUZZ = 12
MIN_PER_REGION = 3


def limits() -> v.LabSessionLimits:
    s = get_settings()
    return v.LabSessionLimits(
        focus_min_speakers=MIN_FOCUS_SPEAKERS, focus_max_speakers=s.lab_t3_focus_max_speakers,
        focus_max_guide_questions=s.lab_t3_focus_max_guide_questions, focus_max_interjections=s.lab_t3_focus_max_interjections,
        buzz_min_participants=MIN_BUZZ, buzz_max_participants=s.lab_t3_buzz_max_participants, buzz_max_rounds=s.lab_t3_buzz_max_rounds,
        message_check_min_per_region=MIN_PER_REGION, message_check_max_per_region=s.lab_t3_message_check_max_per_region,
        message_check_max_regions=s.lab_t3_message_check_max_regions, message_check_max_key_points=MAX_KEY_POINTS)


async def brief_primary_message(s: AsyncSession, campaign_id: UUID) -> str | None:
    """The primary message of the campaign's newest brief, when it has one."""
    row = (await s.execute(select(m.CampaignBriefRow).where(m.CampaignBriefRow.campaign_id == campaign_id)
                           .order_by(m.CampaignBriefRow.version_number.desc()).limit(1))).scalar_one_or_none()
    text = (row.content or {}).get("primary_message") if row else None
    return str(text).strip() or None if text else None


async def session_defaults(user_id: UUID, campaign_id: UUID) -> v.LabSessionDefaults:
    async with read_session() as s:
        campaign, _ = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        message = await brief_primary_message(s, campaign.id)
    return v.LabSessionDefaults(
        guide=list(DEFAULT_GUIDE[:DEFAULT_GUIDE_SIZE]), platforms=[v.LabPlatformOption(value=k, label=label) for k, label in PLATFORMS],  # type: ignore[arg-type]
        primary_message=message, primary_message_source="brief" if message else None,
        key_points=split_key_points(message) if message else [], limits=limits())


async def resolve_creative(
    s: AsyncSession, user_id: UUID, campaign: m.Campaign, content_version_id: UUID | None, inline: CampaignContent | None,
) -> tuple[dict[str, Any], UUID | None]:
    """The copy a session runs on: the inline copy, else the stored content version (the current one by default)."""
    if inline is not None:
        return inline.model_dump(mode="json"), None
    version = await audience._content_version(s, user_id, campaign, content_version_id)
    return CampaignContent.model_validate(version.content).model_dump(mode="json"), version.id


def sample_by_state(
    *, size: int, states: Sequence[str], languages: Sequence[str] | None, city_tiers: Sequence[str] | None,
    age_bands: Sequence[str] | None, seed: int, weights: dict[str, dict[str, float]] | None,
) -> tuple[list[SampledParticipant], dict[str, Any]]:
    """A panel drawn state by state, so each participant reads and speaks a language of their own state (or one the person
    named). The size is split across the states by the plan's state weights (equal by default); ordinals run on from 0.
    Returns the people and the dimension lists the panel description records."""
    shares = [(weights or {}).get("states", {}).get(c, 1.0) for c in states]
    counts = allocate(shares, size)
    kept = {k: weights[k] for k, listed in (("languages", languages), ("city_tiers", city_tiers), ("age_bands", age_bands))
            if listed and weights and k in weights}  # a share only applies to a list the person named
    people: list[SampledParticipant] = []
    used_languages: list[str] = []
    for i, (code, n) in enumerate(zip(states, counts)):
        if n == 0:
            continue
        langs = list(languages) if languages else audience._region_languages(code)
        used_languages += [lang for lang in langs if lang not in used_languages]
        part = sample_panel(size=n, states=[code], languages=langs, city_tiers=city_tiers or CITY_TIERS, age_bands=age_bands or AGE_BANDS,
                            seed=seed + 1009 * i, weights=kept or None)
        people += [replace(p, ordinal=len(people) + k) for k, p in enumerate(part)]
    dims = {"states": list(states), "languages": used_languages, "city_tiers": list(city_tiers or CITY_TIERS),
            "age_bands": list(age_bands or AGE_BANDS), "weights": weights}
    return people, dims


# --- the demo hook ---------------------------------------------------------------------------------------------------------

_instant: ContextVar[bool] = ContextVar("lab_t3_instant", default=False)


def replay_is_instant() -> bool:
    """True while the demo seed runs: its sessions are saved at once instead of being paced like a live session."""
    return _instant.get()


@dataclass(frozen=True)
class DemoVersion:
    """One version of the Aamod journey: where it runs, the finished Quick Read panel beside it, and the copy."""

    region_code: str
    quick_read_run_id: UUID
    version_ref: str
    creative: dict[str, Any]


async def _await_run(run_id: UUID, what: str, timeout: float = 120.0) -> None:
    async with asyncio.timeout(timeout):
        while True:
            async with read_session() as s:
                run = await s.get(m.AudienceRun, run_id)
            if run is not None and run.status in ("completed", "partial", "failed", "cancelled"):
                break
            await asyncio.sleep(0.05)
    if run.status != "completed":
        raise RuntimeError(f"The demo {what} did not complete (status {run.status}).")


async def _spread_of_panel(run_id: UUID, seats: int = 5) -> list[UUID] | None:
    """Speakers for the demo discussion: one voice per kind of stored reaction before any is repeated, so the table has an
    opposed view to disagree with. None (let the server pick) when the panel has fewer than two responses."""
    async with read_session() as s:
        rows = await audience._participants(s, run_id)
    by_stance: dict[str, list[UUID]] = {}
    for r in rows:
        if r.response:
            by_stance.setdefault(audience._stance_of(r, "quick_read") or "neutral", []).append(r.id)
    order = ("confused", "negative", "positive", "mixed", "neutral")
    chosen: list[UUID] = []
    while len(chosen) < seats and any(by_stance.get(k) for k in order):
        for k in order:
            if by_stance.get(k) and len(chosen) < seats:
                chosen.append(by_stance[k].pop(0))
    return chosen if len(chosen) >= 2 else None


async def seed_demo_sessions(
    user_id: UUID, campaign_id: UUID, versions: Sequence[DemoVersion], *, intended_message: str
) -> dict[str, UUID]:
    """Fill a demo project with one finished session of each kind, from fixtures and with no provider call.

    `versions` is the original first, then each adapted region, each with its Quick Read panel. The Focus Group talks to the first
    adapted region's panel, Buzz passes the original on across every region listed, and Message Check tests each adapted region's copy
    against `intended_message`. Called by `services.demo_journey` after the Quick Reads exist. Runs one after another and returns
    their run ids by kind."""
    from app.schemas.audience import SamplingPlan
    from app.schemas.lab_buzz import BuzzCreate
    from app.schemas.lab_focus_group import FocusGroupCreate
    from app.schemas.lab_message_check import MessageCheckCreate, MessageCheckTarget
    from app.services import lab_buzz, lab_focus_group, lab_message_check

    original, adapted = versions[0], list(versions[1:]) or [versions[0]]
    talking = next((v for v in adapted if v.region_code == "IN-KL"), adapted[0])  # the festival-neutral Kerala version reads weakest
    token = _instant.set(True)  # the tasks the runs start copy this context
    try:
        talk = await lab_focus_group.start_focus_group(user_id, campaign_id, FocusGroupCreate(
            panel_run_id=talking.quick_read_run_id, participant_ids=await _spread_of_panel(talking.quick_read_run_id),
            guide=list(DEFAULT_GUIDE[:3]), seed=42))
        await _await_run(talk.run_id, "focus group")
        buzz = await lab_buzz.start_buzz(user_id, campaign_id, BuzzCreate(
            sampling=SamplingPlan(states=[v.region_code for v in versions]), size=24, rounds=3, platform="instagram", initial_exposure=0.35,
            creative=CampaignContent.model_validate(original.creative), version_ref=original.version_ref,
            intended_message=intended_message, seed=42))
        await _await_run(buzz.run_id, "buzz simulation")
        check = await lab_message_check.start_message_check(user_id, campaign_id, MessageCheckCreate(
            targets=[MessageCheckTarget(region_code=v.region_code, version_ref=v.version_ref,
                                        creative=CampaignContent.model_validate(v.creative)) for v in adapted],
            intended_message=intended_message, size_per_region=8, seed=42))
        await _await_run(check.run_id, "message check")
    finally:
        _instant.reset(token)
    return {"focus_group": talk.run_id, "buzz_sim": buzz.run_id, "message_check": check.run_id}
