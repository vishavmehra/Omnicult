"""Audience Lab service: starts, runs and reads Quick Read, Audience Study and Risk Check; Ask the Panel; and the human
status of Risk Check findings.

Runs execute in-process (like the main run engine) but keep their own lifecycle in `audience_runs`: a start request
validates and snapshots everything the run depends on (the creative, the region's claims as they stood, the sampled
panel), records the run, and returns 202; the workflow then works from that snapshot only. A retried request with the same
Idempotency-Key returns the run it already created. A run past its lease is reclaimed as interrupted the next time anyone
starts one, so a restart cannot strand a user's run quota.

Access follows `services.common`: a campaign in a workspace the caller does not belong to is a 404; viewers and reviewers
read but do not start runs; reviewers may set finding statuses.
"""

import asyncio
import logging
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.panel import (
    AGE_BANDS,
    CITY_TIERS,
    PROTECTED_TRAITS,
    SAMPLING_NOTE,
    SAMPLING_VERSION,
    SampledParticipant,
    describe,
    marginal_counts,
    sample_panel,
)
from app.analytics.population import stance_distribution
from app.analytics.risk_rules import RULES_VERSION
from app.core.config import get_settings
from app.core.errors import Conflict, Forbidden, ProviderFailed, ProviderNotConfigured, ProviderTimeout, RateLimited, ValidationFailed
from app.core.idempotency import idempotency_key_var
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.llm.gateway import LLMError, LLMGateway
from app.reference.ad_codes import load_index
from app.reference.india import LANGUAGES, REGIONS
from app.schemas import audience as v
from app.schemas.campaigns import CampaignContent
from app.schemas.common import ErrorDetail, Market, StepTrace
from app.schemas.population import MemoryItem, ParticipantDetail, ParticipantState
from app.schemas.runs import RunError, RunProgress
from app.services import claims as claim_service
from app.services.audit import record_audit
from app.services.campaigns import current_version
from app.services.common import ARCHIVED, conflict, get_owned, not_found, paginate, require_writable, touch
from app.services.identity import READ_ONLY, REVIEW_ROLES
from app.services.metering import AiUsage, record_ai_usage
from app.services.projects import to_brand
from app.workflows import followup
from app.workflows.audience_types import (
    AudienceStudyInput,
    PanelMember,
    QuickReadInput,
    RiskCheckInput,
)
from app.workflows.quick_read import run_audience_study, run_quick_read
from app.workflows.risk_check import run_risk_check
from app.workflows.types import BrandContext, WorkflowContext

logger = logging.getLogger("omnicult.audience")

API = "/api/v1"
ACTIVE = ("queued", "running")
USABLE = ("completed", "partial")
MAX_CONCURRENT_RUNS = 3
ASK_BATCH = 8
ASK_HISTORY = 20
REGION_NAME = {r.code: r.name for r in REGIONS}
REGION_ROW = {r.code: r for r in REGIONS}
LANGUAGE_NAME = {row.code: row.name for row in LANGUAGES}
GROUNDING_NOTE = (
    "A statement marked claim_supported cites at least one observed or calculated claim stored for the region. Every other "
    "statement is a model interpretation. Confidence on a claim comes from its sources, never from the model."
)
COST_NOTE = "Estimated from the price table where usage is reported; not a provider invoice. Null when unknown."
INTERRUPTED = RunError(
    code="RUN_INTERRUPTED", message="The server restarted before this run finished. No results were saved; retrying is safe.",
    retryable=True)
UNEXPECTED = RunError(
    code="INTERNAL_ERROR", message="An unexpected error stopped this run. No results were saved; retrying is safe.", retryable=True)


# --- seams for tests and providers ----------------------------------------------------------------------------------


def llm_ready(mode: str) -> bool:
    """Whether the run can use a model: demo always (fixtures), live only when a provider is configured."""
    return True if mode == "demo" else LLMGateway(get_settings()).is_configured()


def make_llm(mode: str) -> LLMGateway:
    """Demo runs get the labelled fixture provider (no network); live runs the configured gateway."""
    if mode == "demo":
        from app.fixtures.audience_llm import fixture_provider

        return LLMGateway(get_settings(), provider=fixture_provider())
    return LLMGateway(get_settings())


# --- executor -------------------------------------------------------------------------------------------------------


class _Executor:
    """Tracks background tasks; rebinds its asyncio primitives when the event loop changes (tests)."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.tasks: set[asyncio.Task[None]] = set()

    def bind(self) -> "_Executor":
        loop = asyncio.get_running_loop()
        if loop is not self.loop:
            self.loop, self.tasks = loop, set()
            self.slots, self.start_lock = asyncio.Semaphore(MAX_CONCURRENT_RUNS), asyncio.Lock()
        return self

    def submit(self, run_id: UUID) -> None:
        task = asyncio.create_task(_execute(run_id), name=f"audience-run-{run_id}")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)


executor = _Executor()


async def wait_idle() -> None:
    """Wait until every Audience Lab run on this loop has finished (tests and shutdown)."""
    engine = executor.bind()
    while engine.tasks:
        await asyncio.wait(list(engine.tasks))


# --- starting runs --------------------------------------------------------------------------------------------------


def _invalid(field: str, message: str) -> ValidationFailed:
    return ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=field, message=message)])


def _check_provider(mode: str) -> None:
    if not llm_ready(mode):
        raise ProviderNotConfigured(
            "Live Audience Lab runs are unavailable: no language model provider is configured on the server. "
            "Use a demo project or configure a provider.")


async def _campaign_for_run(s: AsyncSession, user_id: UUID, campaign_id: UUID) -> tuple[m.Campaign, m.Project]:
    campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
    require_writable(project)
    _check_provider(project.mode)
    return campaign, project


async def _content_version(
    s: AsyncSession, user_id: UUID, campaign: m.Campaign, version_id: UUID | None
) -> m.CampaignVersion:
    if version_id is None:
        return await current_version(s, campaign.id)
    version, _ = await get_owned(s, m.CampaignVersion, version_id, user_id, "Content version", "content_version_id")
    if version.campaign_id != campaign.id:
        raise conflict("content_version_id", "The content version belongs to another campaign.")
    return version


async def claims_snapshot(
    user_id: UUID, project: m.Project, region_codes: Sequence[str]
) -> tuple[list[v.GroundingClaim], dict[str, str]]:
    """The region's claims as they stand (the same profile the Evidence Meter reads), and each region's evidence strength.
    A project outside any workspace has no claims to read."""
    if project.workspace_id is None:
        return [], {}
    claims: list[v.GroundingClaim] = []
    strength: dict[str, str] = {}
    for code in region_codes:
        profile = await claim_service.build_region_profile(user_id, project.workspace_id, code, mode=project.mode)
        strength[code] = profile.meter.strength
        for group in profile.categories:
            claims += [
                v.GroundingClaim(
                    id=c.id, region_code=code, category=c.category, attribute=c.attribute, value_text=c.value_text,
                    kind=c.kind, confidence=c.effective_confidence)
                for c in group.claims if c.status in ("active", "needs_review")
            ]
    return claims, strength


def _brand_snapshot(brand: m.BrandKit) -> dict[str, Any]:
    return to_brand(brand).model_dump(mode="json", exclude={"id", "updated_at"})


def _copy(content: dict[str, Any]) -> v.CreativeCopy:
    return v.CreativeCopy(headline=content.get("headline"), body=content.get("body"), call_to_action=content.get("call_to_action"))


def _sampling(plan: v.SamplingPlan, default_states: list[str], default_languages: list[str]) -> dict[str, Any]:
    return {
        "states": plan.states or default_states, "languages": plan.languages or default_languages,
        "city_tiers": plan.city_tiers or list(CITY_TIERS), "age_bands": plan.age_bands or list(AGE_BANDS),
        "weights": plan.weights,
    }


def _region_languages(code: str) -> list[str]:
    row = REGION_ROW[code]
    return list(dict.fromkeys([row.primary, *row.secondary]))[:6]


def _panel_rows(run_id: UUID, people: Sequence[SampledParticipant]) -> list[m.PanelParticipant]:
    rows = []
    for p in people:
        rows.append(m.PanelParticipant(
            id=p.id(run_id), run_id=run_id, ordinal=p.ordinal, state_code=p.state_code, state_name=REGION_NAME[p.state_code],
            language=p.language, language_name=LANGUAGE_NAME.get(p.language, p.language), city_tier=p.city_tier,
            age_band=p.age_band, traits=p.traits, is_synthetic=True,
            persona=describe(REGION_NAME[p.state_code], LANGUAGE_NAME.get(p.language, p.language), p.city_tier, p.age_band)))
    return rows


def _panel_inputs(size: int, dims: dict[str, Any], people: Sequence[SampledParticipant], seed: int) -> dict[str, Any]:
    return {
        "requested_size": size, "generated_size": len(people), "states": dims["states"], "languages": dims["languages"],
        "city_tiers": dims["city_tiers"], "age_bands": dims["age_bands"], "weights": dims["weights"],
        "marginal_counts": marginal_counts(people), "seed": seed, "sampling_version": SAMPLING_VERSION, "method": SAMPLING_NOTE,
    }


async def _create_run(
    user_id: UUID, project: m.Project, campaign: m.Campaign, kind: str, *, run_id: UUID, config: dict[str, Any],
    inputs: dict[str, Any], region_codes: list[str], content_version_id: UUID | None, version_ref: str | None,
    seed: int | None, participants: list[m.PanelParticipant] = (),  # type: ignore[assignment]
) -> v.AudienceRunAccepted:
    engine = executor.bind()
    key = idempotency_key_var.get()
    now = utcnow()
    async with engine.start_lock:  # count and insert atomically on this instance
        async with session() as s, s.begin():
            await _reclaim_expired(s)
            if key is not None:  # a retried request returns the run it already created
                earlier = await s.scalar(select(m.AudienceRun).where(
                    m.AudienceRun.created_by == user_id, m.AudienceRun.idempotency_key == key))
                if earlier is not None:
                    if (earlier.campaign_id, earlier.kind) != (campaign.id, kind):
                        raise Conflict("This Idempotency-Key was already used for a different request.")
                    return _accepted(earlier)
            await _check_active_limit(s, user_id)
            run = m.AudienceRun(
                id=run_id, workspace_id=project.workspace_id, project_id=project.id, campaign_id=campaign.id, kind=kind,
                status="queued", mode=project.mode, region_codes=region_codes, content_version_id=content_version_id,
                version_ref=version_ref, seed=seed, config=config, inputs=inputs, steps=[], limitations=[],
                created_by=user_id, idempotency_key=key, created_at=now,
                lease_expires_at=now + timedelta(seconds=get_settings().audience_run_timeout_seconds + 60))
            s.add(run)
            try:
                await s.flush()
            except IntegrityError:  # the same key arrived on another instance at the same moment
                raise Conflict("A request with this Idempotency-Key is already in progress. Retry shortly.") from None
            if participants:
                s.add_all(participants)
                await s.flush()
            await record_audit(
                s, action=f"audience.{kind}.start", target_type="audience_run", target_id=str(run_id),
                workspace_id=project.workspace_id, actor_user_id=user_id, detail={"mode": project.mode, "regions": region_codes})
            touch(await s.get(m.Project, project.id))  # type: ignore[arg-type]
    engine.submit(run_id)
    return v.AudienceRunAccepted(run_id=run_id, kind=kind, status="queued", status_url=_url(campaign.id, kind, run_id))  # type: ignore[arg-type]


def _url(campaign_id: UUID, kind: str, run_id: UUID) -> str:
    path = {"quick_read": "quick-reads", "audience_study": "audience-studies", "risk_check": "risk-checks"}[kind]
    return f"{API}/campaigns/{campaign_id}/{path}/{run_id}"


def _accepted(run: m.AudienceRun) -> v.AudienceRunAccepted:
    return v.AudienceRunAccepted(run_id=run.id, kind=run.kind, status=run.status, status_url=_url(run.campaign_id, run.kind, run.id))  # type: ignore[arg-type]


async def _reclaim_expired(s: AsyncSession) -> None:
    """Fail runs whose lease has passed (a restart or a crash), so they cannot hold a user's run quota forever."""
    await s.execute(
        update(m.AudienceRun)
        .where(m.AudienceRun.status.in_(ACTIVE), m.AudienceRun.lease_expires_at < utcnow())
        .values(status="failed", error=INTERRUPTED.model_dump(mode="json"), completed_at=utcnow())
    )


async def _check_active_limit(s: AsyncSession, user_id: UUID) -> None:
    active = await s.scalar(select(func.count(m.AudienceRun.id)).where(
        m.AudienceRun.created_by == user_id, m.AudienceRun.status.in_(ACTIVE)))
    limit = get_settings().max_active_runs_per_user
    if (active or 0) >= limit:
        raise RateLimited(f"You already have {active} active Audience Lab runs (limit {limit}). Wait for one to finish, then try again.")


async def start_quick_read(user_id: UUID, campaign_id: UUID, body: v.QuickReadCreate) -> v.AudienceRunAccepted:
    settings = get_settings()
    if body.region_code not in REGION_NAME:
        raise _invalid("region_code", f"{body.region_code} is not a known Indian state or union territory.")
    if body.size > settings.audience_quick_read_max_participants:
        raise _invalid("size", f"Quick Read is limited to {settings.audience_quick_read_max_participants} participants; use an Audience Study for more.")
    if body.sampling.states and body.sampling.states != [body.region_code]:
        raise _invalid("sampling.states", "Quick Read covers one region: omit states, or list only the region.")
    dims = _sampling(body.sampling, [body.region_code], _region_languages(body.region_code))
    async with read_session() as s:
        campaign, project = await _campaign_for_run(s, user_id, campaign_id)
        version = await _content_version(s, user_id, campaign, body.content_version_id)
        brand = await _brand_of(s, project.id)
    claims, strength = await claims_snapshot(user_id, project, [body.region_code])
    people = sample_panel(size=body.size, states=dims["states"], languages=dims["languages"], city_tiers=dims["city_tiers"],
                          age_bands=dims["age_bands"], seed=body.seed, weights=dims["weights"])
    run_id = uuid4()
    inputs = {
        "region": {"code": body.region_code, "name": REGION_NAME[body.region_code]}, "creative": version.content,
        "intended_message": body.intended_message, "claims": [c.model_dump(mode="json") for c in claims],
        "evidence_strength": strength, "brand": _brand_snapshot(brand), "panel": _panel_inputs(body.size, dims, people, body.seed),
    }
    return await _create_run(
        user_id, project, campaign, "quick_read", run_id=run_id, config=body.model_dump(mode="json"), inputs=inputs,
        region_codes=[body.region_code], content_version_id=version.id, version_ref=body.version_ref, seed=body.seed,
        participants=_panel_rows(run_id, people))


async def start_audience_study(user_id: UUID, campaign_id: UUID, body: v.AudienceStudyCreate) -> v.AudienceRunAccepted:
    settings = get_settings()
    states = body.sampling.states or []
    unknown = [c for c in states if c not in REGION_NAME]
    if unknown:
        raise _invalid("sampling.states", f"Unknown state or union territory code(s): {', '.join(unknown)}.")
    if body.size > settings.audience_study_max_participants:
        raise _invalid("size", f"Audience Study is limited to {settings.audience_study_max_participants} participants on this server.")
    default_languages = list(dict.fromkeys(l for c in states for l in _region_languages(c)))[:6]
    dims = _sampling(body.sampling, states, default_languages)
    async with read_session() as s:
        campaign, project = await _campaign_for_run(s, user_id, campaign_id)
        version = await _content_version(s, user_id, campaign, body.content_version_id)
        brand = await _brand_of(s, project.id)
    claims, strength = await claims_snapshot(user_id, project, states)
    people = sample_panel(size=body.size, states=dims["states"], languages=dims["languages"], city_tiers=dims["city_tiers"],
                          age_bands=dims["age_bands"], seed=body.seed, weights=dims["weights"])
    run_id = uuid4()
    inputs = {
        "regions": [{"code": c, "name": REGION_NAME[c]} for c in states], "creative": version.content,
        "intended_message": body.intended_message, "claims": [c.model_dump(mode="json") for c in claims],
        "evidence_strength": strength, "brand": _brand_snapshot(brand), "depth": body.interview_depth,
        "panel": _panel_inputs(body.size, dims, people, body.seed),
    }
    return await _create_run(
        user_id, project, campaign, "audience_study", run_id=run_id, config=body.model_dump(mode="json"), inputs=inputs,
        region_codes=list(states), content_version_id=version.id, version_ref=body.version_ref, seed=body.seed,
        participants=_panel_rows(run_id, people))


def _elements_from(content: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for kind, field in (("headline", "headline"), ("body", "body"), ("cta", "call_to_action")):
        if content.get(field):
            out.append({"id": kind, "kind": kind, "value": content[field], "language": None, "script": None, "bbox": None,
                        "scene_id": None, "locked": False})
    return out


async def start_risk_check(user_id: UUID, campaign_id: UUID, body: v.RiskCheckCreate) -> v.AudienceRunAccepted:
    if body.region_code not in REGION_NAME:
        raise _invalid("region_code", f"{body.region_code} is not a known Indian state or union territory.")
    async with read_session() as s:
        campaign, project = await _campaign_for_run(s, user_id, campaign_id)
        version_id, elements = None, [e.model_dump(mode="json") for e in body.elements or []]
        if not elements:
            version = await _content_version(s, user_id, campaign, body.content_version_id)
            version_id, elements = version.id, _elements_from(version.content)
        brand = await _brand_of(s, project.id)
    claims, strength = await claims_snapshot(user_id, project, [body.region_code])
    index = load_index()
    inputs = {
        "region": {"code": body.region_code, "name": REGION_NAME[body.region_code]}, "elements": elements,
        "scenes": [s.model_dump(mode="json") for s in body.scenes], "product_category": body.product_category,
        "claims": [c.model_dump(mode="json") for c in claims], "evidence_strength": strength,
        "brand": _brand_snapshot(brand), "ad_code_index": {"version": index.version, "retrieved_at": index.retrieved_at},
    }
    return await _create_run(
        user_id, project, campaign, "risk_check", run_id=uuid4(), config=body.model_dump(mode="json"), inputs=inputs,
        region_codes=[body.region_code], content_version_id=version_id, version_ref=body.version_ref, seed=None)


async def _brand_of(s: AsyncSession, project_id: UUID) -> m.BrandKit:
    return (await s.execute(select(m.BrandKit).where(m.BrandKit.project_id == project_id))).scalar_one()


# --- executing runs -------------------------------------------------------------------------------------------------


async def _execute(run_id: UUID) -> None:
    timeout = get_settings().audience_run_timeout_seconds
    try:
        async with executor.bind().slots:
            if not await _mark_running(run_id):
                return
            async with asyncio.timeout(timeout):
                kind, workflow_input, mode = await _build_input(run_id)
                llm, progress = make_llm(mode), _progress_callback(run_id)
                if kind == "quick_read":
                    outcome = await run_quick_read(workflow_input, llm, progress)
                elif kind == "audience_study":
                    outcome = await run_audience_study(workflow_input, llm, progress)
                else:
                    outcome = await run_risk_check(workflow_input, llm, progress)
            await _persist(run_id, kind, outcome)
    except asyncio.CancelledError:
        await _fail(run_id, INTERRUPTED)
        raise
    except TimeoutError:
        await _fail(run_id, RunError(
            code="RUN_FAILED", retryable=True,
            message=f"The run exceeded the {timeout // 60}-minute limit. No results were saved; retrying is safe."))
    except Exception:
        logger.exception("Audience Lab run failed unexpectedly", extra={"run_id": str(run_id)})
        await _fail(run_id, UNEXPECTED)


STAGE_COUNT = {"quick_read": 3, "audience_study": 4, "risk_check": 3}
FIRST_STAGE = {"quick_read": "loading_context", "audience_study": "loading_context", "risk_check": "loading_inputs"}


async def _mark_running(run_id: UUID) -> bool:
    async with session() as s, s.begin():
        run = await s.get(m.AudienceRun, run_id)
        if run is None or run.status != "queued":
            return False
        run.status, run.started_at = "running", utcnow()
        run.progress = RunProgress(stage=FIRST_STAGE[run.kind], completed_steps=0, total_steps=STAGE_COUNT[run.kind],
                                   message="Starting.").model_dump()
    return True


def _progress_callback(run_id: UUID) -> Any:
    async def progress(stage: str, completed_steps: int, total_steps: int, message: str) -> None:
        try:
            value = RunProgress(stage=stage, completed_steps=completed_steps, total_steps=total_steps, message=message)
            async with session() as s, s.begin():
                await s.execute(update(m.AudienceRun).where(m.AudienceRun.id == run_id, m.AudienceRun.status == "running")
                                .values(progress=value.model_dump()))
        except Exception:  # progress is best-effort and must never break the run
            logger.warning("Progress update skipped", extra={"run_id": str(run_id), "stage": stage}, exc_info=True)

    return progress


async def _build_input(run_id: UUID) -> tuple[str, Any, str]:
    async with read_session() as s:
        run = await s.get(m.AudienceRun, run_id)
        assert run is not None
        inputs = run.inputs
        context = WorkflowContext(run_id=run.id, project_id=run.project_id, campaign_id=run.campaign_id, mode=run.mode,
                                  brand=BrandContext.model_validate(inputs["brand"]))
        claims = [v.GroundingClaim.model_validate(c) for c in inputs["claims"]]
        if run.kind == "risk_check":
            return run.kind, RiskCheckInput(
                context=context, region=v.RegionRef.model_validate(inputs["region"]), product_category=inputs["product_category"],
                elements=[v.CreativeElementIn.model_validate(e) for e in inputs["elements"]],
                scenes=[v.CreativeSceneIn.model_validate(x) for x in inputs["scenes"]], claims=claims), run.mode
        rows = (await s.execute(select(m.PanelParticipant).where(m.PanelParticipant.run_id == run_id)
                                .order_by(m.PanelParticipant.ordinal))).scalars().all()
        members = [PanelMember(
            id=r.id, ordinal=r.ordinal, state_code=r.state_code, state_name=r.state_name, language=r.language,
            language_name=r.language_name, city_tier=r.city_tier, age_band=r.age_band, traits=r.traits, persona=r.persona)
            for r in rows]
        creative = CampaignContent.model_validate(inputs["creative"])
        if run.kind == "quick_read":
            return run.kind, QuickReadInput(
                context=context, region=v.RegionRef.model_validate(inputs["region"]), creative=creative,
                intended_message=inputs["intended_message"], participants=members, claims=claims, seed=run.seed or 0), run.mode
        return run.kind, AudienceStudyInput(
            context=context, regions=[v.RegionRef.model_validate(r) for r in inputs["regions"]],
            content_version_id=run.content_version_id, creative=creative, intended_message=inputs["intended_message"],  # type: ignore[arg-type]
            participants=members, claims=claims, depth=inputs["depth"], seed=run.seed or 0), run.mode


def _usage_totals(steps: Sequence[StepTrace]) -> v.UsageTotals:
    def total(field: str) -> int | None:
        values = [getattr(s.usage, field) if s.usage else None for s in steps if _called_model(s)]
        known = [x for x in values if x is not None]
        return sum(known) if known and len(known) == len(values) else None

    costs = [s.usage.estimated_cost_usd for s in steps if _called_model(s) and s.usage and s.usage.estimated_cost_usd is not None]
    return v.UsageTotals(input_tokens=total("input_tokens"), output_tokens=total("output_tokens"),
                         estimated_cost_usd=round(sum(costs), 6) if costs else None,
                         model_stages=sum(1 for s in steps if _called_model(s)), cost_note=COST_NOTE)


def _called_model(step: StepTrace) -> bool:
    return step.provider not in (None, "omnicult", "fixture")


async def _persist(run_id: UUID, kind: str, outcome: Any) -> None:
    now = utcnow()
    async with session() as s, s.begin():
        run = await s.get(m.AudienceRun, run_id)
        if run is None or run.status != "running":
            return
        if kind == "quick_read":
            rows = {p.id: p for p in (await s.execute(select(m.PanelParticipant).where(m.PanelParticipant.run_id == run_id))).scalars()}
            for pid, response in outcome.responses.items():
                rows[pid].response = response.model_dump(mode="json")
            run.result = {"summary": outcome.summary.model_dump(mode="json") if outcome.summary else None,
                          "grounding": outcome.grounding.model_dump(mode="json")}
        elif kind == "audience_study":
            rows = {p.id: p for p in (await s.execute(select(m.PanelParticipant).where(m.PanelParticipant.run_id == run_id))).scalars()}
            for pid, interview in outcome.interviews.items():
                rows[pid].response = interview.model_dump(mode="json")
            run.result = {"summary": outcome.summary.model_dump(mode="json") if outcome.summary else None}
        else:
            for n, f in enumerate(outcome.findings):
                s.add(m.RiskFindingRow(
                    id=uuid4(), run_id=run_id, ordinal=n, element_id=f.element_id, category=f.category, severity=f.severity,
                    blocks_go=f.blocks_go, confidence_label=f.confidence_label, anchor=f.anchor.model_dump(mode="json"),
                    quote=f.quote, quote_start=f.quote_start, quote_end=f.quote_end, verification=f.verification,
                    observation=f.observation, interpretation=f.interpretation, suggested_fix=f.suggested_fix,
                    ad_codes=[a.model_dump(mode="json") for a in f.ad_codes], claim_ids=[str(c) for c in f.claim_ids],
                    source=f.source, severity_rules=f.severity_rules, rules_version=RULES_VERSION, status="open",
                    limitations=f.limitations, created_at=now))
            run.result = {"dropped": outcome.dropped.model_dump(mode="json") | {"total": outcome.dropped.total},
                          "cited_claim_ids": [str(c) for c in outcome.cited_claim_ids]}
        run.status = outcome.status
        run.error = outcome.error.model_dump(mode="json") if outcome.error else (
            RunError(code="RUN_FAILED", message="The workflow failed without a reported cause.", retryable=True).model_dump(mode="json")
            if outcome.status == "failed" else None)
        run.steps = [st.model_dump(mode="json") for st in outcome.steps]
        run.usage = _usage_totals(outcome.steps).model_dump(mode="json")
        run.limitations = list(outcome.limitations)
        total = STAGE_COUNT[kind]
        run.progress = RunProgress(
            stage="completed" if outcome.status in USABLE else (run.progress or {}).get("stage", FIRST_STAGE[kind]),
            completed_steps=total if outcome.status in USABLE else (run.progress or {}).get("completed_steps", 0),
            total_steps=total,
            message=("Complete." if outcome.status == "completed" else "Finished with partial results; see the limitations.")
            if outcome.status in USABLE else "Stopped.").model_dump()
        if run.mode == "demo" and outcome.status in USABLE:
            run.progress["message"] = run.progress["message"][:-1] + " (demo fixtures)."
        run.completed_at = now
        for st in outcome.steps:  # one usage event per stage that called a real model
            if _called_model(st):
                await record_ai_usage(AiUsage(
                    capability="text", provider=st.provider or "unknown", model=st.model_id or "unknown",
                    prompt_version=st.prompt_version, input_tokens=(st.usage.input_tokens or 0) if st.usage else 0,
                    output_tokens=(st.usage.output_tokens or 0) if st.usage else 0,
                    estimated_cost_usd=(st.usage.estimated_cost_usd or 0.0) if st.usage else 0.0, latency_ms=st.latency_ms,
                    status="ok" if st.status == "completed" else "error", error_code=st.error_code,
                    workspace_id=run.workspace_id, project_id=run.project_id, campaign_id=run.campaign_id, user_id=run.created_by,
                ), s=s)


async def _fail(run_id: UUID, error: RunError) -> None:
    """Record a terminal failure, retried briefly: a run left active would hold the user's run quota."""
    for attempt in range(3):
        try:
            async with session() as s, s.begin():
                run = await s.get(m.AudienceRun, run_id)
                if run is not None and run.status in ACTIVE:
                    run.status, run.completed_at = "failed", utcnow()
                    run.error = error.model_copy(update={"stage": (run.progress or {}).get("stage")}).model_dump(mode="json")
            return
        except Exception:
            if attempt == 2:
                logger.exception("Could not record run failure", extra={"run_id": str(run_id)})
            else:
                await asyncio.sleep(0.5 * (attempt + 1))


# --- reading runs ---------------------------------------------------------------------------------------------------


async def _run_in(s: AsyncSession, user_id: UUID, campaign_id: UUID, run_id: UUID, kinds: Sequence[str]) -> tuple[m.AudienceRun, m.Project]:
    campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
    run = await s.get(m.AudienceRun, run_id)
    if run is None or run.campaign_id != campaign.id or run.kind not in kinds:
        raise not_found("Run")
    return run, project


def _metadata(run: m.AudienceRun) -> v.AudienceRunMetadata:
    steps = [StepTrace.model_validate(x) for x in run.steps]
    usage = v.UsageTotals.model_validate(run.usage) if run.usage else v.UsageTotals(
        input_tokens=None, output_tokens=None, estimated_cost_usd=None, model_stages=0, cost_note=COST_NOTE)
    return v.AudienceRunMetadata(
        run_id=run.id, kind=run.kind, mode=run.mode, seed=run.seed, started_at=run.started_at,  # type: ignore[arg-type]
        completed_at=run.completed_at,
        providers=list(dict.fromkeys(s.provider for s in steps if s.provider and s.provider != "omnicult")),
        model_ids=list(dict.fromkeys(s.model_id for s in steps if s.model_id)),
        prompt_versions=list(dict.fromkeys(s.prompt_version for s in steps if s.prompt_version)), usage=usage, steps=steps)


def _grounding(run: m.AudienceRun) -> v.GroundingSummary:
    claims = [v.GroundingClaim.model_validate(c) for c in run.inputs["claims"]]
    stats = (run.result or {}).get("grounding", {})
    cited = [UUID(c) for c in stats.get("cited_claim_ids", (run.result or {}).get("cited_claim_ids", []))]
    return v.GroundingSummary(
        region_codes=list(run.region_codes), claims_supplied=len(claims), claims=claims,
        evidence_strength=run.inputs.get("evidence_strength", {}), cited_claim_ids=cited,
        claim_supported_statements=stats.get("claim_supported", 0), interpretation_statements=stats.get("interpretation", 0),
        note=GROUNDING_NOTE)


def _panel_description(run: m.AudienceRun) -> v.PanelDescription:
    p = run.inputs["panel"]
    return v.PanelDescription(
        requested_size=p["requested_size"], generated_size=p["generated_size"],
        states=[v.RegionRef(code=c, name=REGION_NAME.get(c, c)) for c in p["states"]], languages=p["languages"],
        city_tiers=p["city_tiers"], age_bands=p["age_bands"], weights=p["weights"], marginal_counts=p["marginal_counts"],
        seed=p["seed"], sampling_version=p["sampling_version"], method=p["method"])


def _participant_base(r: m.PanelParticipant) -> dict[str, Any]:
    return dict(id=r.id, ordinal=r.ordinal, state_code=r.state_code, state_name=r.state_name, language=r.language,
                language_name=r.language_name, city_tier=r.city_tier, age_band=r.age_band, persona=r.persona, traits=r.traits)


async def _participants(s: AsyncSession, run_id: UUID) -> list[m.PanelParticipant]:
    return list((await s.execute(select(m.PanelParticipant).where(m.PanelParticipant.run_id == run_id)
                                 .order_by(m.PanelParticipant.ordinal))).scalars())


def _progress(run: m.AudienceRun) -> RunProgress | None:
    return RunProgress.model_validate(run.progress) if run.progress else None


def _error(run: m.AudienceRun) -> RunError | None:
    return RunError.model_validate(run.error) if run.error else None


async def quick_read_result(s: AsyncSession, run: m.AudienceRun) -> v.QuickReadResult:
    rows = await _participants(s, run.id)
    summary = (run.result or {}).get("summary")
    return v.QuickReadResult(
        id=run.id, campaign_id=run.campaign_id, project_id=run.project_id, status=run.status,  # type: ignore[arg-type]
        mode=run.mode, region=v.RegionRef.model_validate(run.inputs["region"]), content_version_id=run.content_version_id,  # type: ignore[arg-type]
        version_ref=run.version_ref, creative=_copy(run.inputs["creative"]), intended_message=run.inputs["intended_message"],
        panel=_panel_description(run),
        participants=[v.QuickReadParticipant(**_participant_base(r), response=v.QuickReadResponse.model_validate(r.response) if r.response else None)
                      for r in rows],
        summary=v.QuickReadSummary.model_validate(summary) if summary else None, grounding=_grounding(run),
        disclosure=v.PanelDisclosure(), limitations=list(run.limitations), error=_error(run), progress=_progress(run),
        run_metadata=_metadata(run), created_at=run.created_at)


async def audience_study_result(s: AsyncSession, run: m.AudienceRun) -> v.AudienceStudyResult:
    rows = await _participants(s, run.id)
    summary = (run.result or {}).get("summary")
    return v.AudienceStudyResult(
        id=run.id, campaign_id=run.campaign_id, project_id=run.project_id, status=run.status,  # type: ignore[arg-type]
        mode=run.mode, content_version_id=run.content_version_id, version_ref=run.version_ref,  # type: ignore[arg-type]
        creative=_copy(run.inputs["creative"]), intended_message=run.inputs["intended_message"],
        interview_depth=run.inputs["depth"], panel=_panel_description(run),
        participants=[v.StudyParticipant(**_participant_base(r), interview=v.StudyInterview.model_validate(r.response) if r.response else None)
                      for r in rows],
        summary=v.StudySummary.model_validate(summary) if summary else None, grounding=_grounding(run),
        disclosure=v.PanelDisclosure(), limitations=list(run.limitations), error=_error(run), progress=_progress(run),
        run_metadata=_metadata(run), created_at=run.created_at)


def to_finding(row: m.RiskFindingRow) -> v.RiskCheckFinding:
    return v.RiskCheckFinding(
        id=row.id, run_id=row.run_id, ordinal=row.ordinal, element_id=row.element_id, category=row.category,  # type: ignore[arg-type]
        severity=row.severity, blocks_go=row.blocks_go, confidence_label=row.confidence_label,  # type: ignore[arg-type]
        anchor=v.Anchor.model_validate(row.anchor), quote=row.quote, quote_start=row.quote_start, quote_end=row.quote_end,
        verification=row.verification, observation=row.observation, interpretation=row.interpretation,  # type: ignore[arg-type]
        suggested_fix=row.suggested_fix, ad_codes=[v.AdCodeRef.model_validate(a) for a in row.ad_codes],
        claim_ids=[UUID(c) for c in row.claim_ids], source=row.source, severity_rules=[v.AppliedRuleView.model_validate(r) for r in row.severity_rules],  # type: ignore[arg-type]
        rules_version=row.rules_version, status=row.status, status_reason=row.status_reason, status_by=row.status_by,  # type: ignore[arg-type]
        status_at=row.status_at, limitations=row.limitations)


def _counts(rows: Sequence[m.RiskFindingRow]) -> v.RiskCounts:
    return v.RiskCounts(
        total=len(rows), by_severity={k: Counter(r.severity for r in rows).get(k, 0) for k in ("low", "medium", "high")},
        by_status={k: Counter(r.status for r in rows).get(k, 0) for k in ("open", "accepted", "dismissed", "fixed")},
        blocking_go=sum(1 for r in rows if r.blocks_go and r.status in ("open", "accepted")))


async def risk_check_result(s: AsyncSession, run: m.AudienceRun) -> v.RiskCheckResult:
    rows = list((await s.execute(select(m.RiskFindingRow).where(m.RiskFindingRow.run_id == run.id)
                                 .order_by(m.RiskFindingRow.ordinal))).scalars())
    dropped = (run.result or {}).get("dropped", {})
    return v.RiskCheckResult(
        id=run.id, campaign_id=run.campaign_id, project_id=run.project_id, status=run.status,  # type: ignore[arg-type]
        mode=run.mode, region=v.RegionRef.model_validate(run.inputs["region"]), content_version_id=run.content_version_id,  # type: ignore[arg-type]
        version_ref=run.version_ref, product_category=run.inputs["product_category"],
        elements=[v.CreativeElementIn.model_validate(e) for e in run.inputs["elements"]],
        scenes=[v.CreativeSceneIn.model_validate(x) for x in run.inputs["scenes"]], rules_version=RULES_VERSION,
        ad_code_index_version=run.inputs["ad_code_index"]["version"], counts=_counts(rows), findings=[to_finding(r) for r in rows],
        dropped=v.DroppedFindings(unverified_quote=dropped.get("unverified_quote", 0), unknown_element=dropped.get("unknown_element", 0),
                                  duplicate=dropped.get("duplicate", 0), total=dropped.get("total", 0)),
        grounding=_grounding(run), limitations=list(run.limitations), error=_error(run), progress=_progress(run),
        run_metadata=_metadata(run), created_at=run.created_at)


async def get_result(user_id: UUID, campaign_id: UUID, run_id: UUID, kind: str) -> Any:
    async with read_session() as s:
        run, _ = await _run_in(s, user_id, campaign_id, run_id, (kind,))
        return await {"quick_read": quick_read_result, "audience_study": audience_study_result, "risk_check": risk_check_result}[kind](s, run)


async def list_runs(user_id: UUID, campaign_id: UUID, kind: str, limit: int, offset: int) -> v.AudienceRunPage:
    async with read_session() as s:
        campaign, _ = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        stmt = select(m.AudienceRun).where(m.AudienceRun.campaign_id == campaign.id, m.AudienceRun.kind == kind)
        rows, total = await paginate(s, stmt.order_by(m.AudienceRun.created_at.desc(), m.AudienceRun.id), limit, offset)
        sizes = {r.id: 0 for r in rows}
        if rows:
            counts = await s.execute(select(m.PanelParticipant.run_id, func.count()).where(
                m.PanelParticipant.run_id.in_(list(sizes))).group_by(m.PanelParticipant.run_id))
            sizes |= dict(counts.all())
            found = await s.execute(select(m.RiskFindingRow.run_id, func.count()).where(
                m.RiskFindingRow.run_id.in_(list(sizes))).group_by(m.RiskFindingRow.run_id))
            findings = dict(found.all())
        else:
            findings = {}
    return v.AudienceRunPage(items=[v.AudienceRunSummary(
        id=r.id, campaign_id=r.campaign_id, kind=r.kind, status=r.status, mode=r.mode,  # type: ignore[arg-type]
        region_codes=list(r.region_codes), participant_count=sizes[r.id], finding_count=findings.get(r.id, 0),
        progress=_progress(r), created_at=r.created_at, completed_at=r.completed_at) for r in rows],
        limit=limit, offset=offset, total=total)


# --- findings -------------------------------------------------------------------------------------------------------


async def list_findings(
    user_id: UUID, campaign_id: UUID, run_id: UUID, *, status: str | None, severity: str | None, category: str | None,
    limit: int, offset: int,
) -> v.RiskCheckFindingPage:
    async with read_session() as s:
        run, _ = await _run_in(s, user_id, campaign_id, run_id, ("risk_check",))
        stmt = select(m.RiskFindingRow).where(m.RiskFindingRow.run_id == run.id)
        for column, value in (("status", status), ("severity", severity), ("category", category)):
            if value is not None:
                stmt = stmt.where(getattr(m.RiskFindingRow, column) == value)
        rows, total = await paginate(s, stmt.order_by(m.RiskFindingRow.ordinal), limit, offset)
    return v.RiskCheckFindingPage(items=[to_finding(r) for r in rows], limit=limit, offset=offset, total=total)


async def update_finding(
    user_id: UUID, campaign_id: UUID, run_id: UUID, finding_id: UUID, body: v.RiskCheckFindingUpdate
) -> v.RiskCheckFinding:
    """A person's decision on one finding. Reviewers may decide; viewers may not. Severity and blocks_go never change."""
    now = utcnow()
    async with session() as s, s.begin():
        run, project = await _run_in(s, user_id, campaign_id, run_id, ("risk_check",))
        if project.access_role not in REVIEW_ROLES:
            raise Forbidden(READ_ONLY)
        if project.status == "archived":
            raise Conflict(ARCHIVED)
        row = await s.get(m.RiskFindingRow, finding_id)
        if row is None or row.run_id != run.id:
            raise not_found("Finding")
        previous = row.status
        row.status, row.status_reason = body.status, (body.reason or "").strip() or None
        row.status_by, row.status_at = (user_id, now) if body.status != "open" else (None, None)
        await record_audit(
            s, action="risk_finding.status", target_type="risk_finding", target_id=str(row.id), workspace_id=run.workspace_id,
            actor_user_id=user_id, detail={"from": previous, "to": body.status, "run_id": str(run.id)})
        await s.flush()
        return to_finding(row)


# --- Ask the Panel --------------------------------------------------------------------------------------------------


def _memories(row: m.PanelParticipant, kind: str, history: list[m.PanelAnswer], questions: dict[UUID, str], when: Any) -> list[MemoryItem]:
    """The participant's stored record as memory, most recent first: earlier answers, then their own response."""
    items = [MemoryItem(kind="follow_up", ref_id=a.id, round_index=None, summary=f"Asked: {questions[a.question_id]} I answered: {a.answer}"[:300],
                        created_at=a.created_at) for a in history]
    r = row.response or {}
    if kind == "quick_read":
        facts = [f"First reaction: {r.get('first_reaction', '')} (overall: {r.get('sentiment')})",
                 f"The message in my own words: {r.get('message', {}).get('restated', '')} ({r.get('message', {}).get('survival')})"]
        for label, key in (("What I liked", "positives"), ("What put me off", "negatives"), ("What confused me", "confusion"),
                           ("Regional concerns I have", "regional_concerns")):
            if r.get(key):
                facts.append(f"{label}: " + "; ".join(p["text"] for p in r[key]))
    else:
        facts = [f"{a['question']} {a['answer']}" for a in r.get("answers", [])]
    items += [MemoryItem(kind="interview", ref_id=row.id, round_index=None, summary=f[:300], created_at=when) for f in facts if f.strip()]
    return items


def _stance_of(row: m.PanelParticipant, kind: str) -> str | None:
    r = row.response or {}
    return r.get("sentiment") if kind == "quick_read" else r.get("reaction")


def _detail(row: m.PanelParticipant, run: m.AudienceRun, history: list[m.PanelAnswer], questions: dict[UUID, str]) -> ParticipantDetail:
    memories = _memories(row, run.kind, history, questions, run.completed_at or run.created_at)
    return ParticipantDetail(
        id=row.id, population_id=run.id, group_id=row.state_code, ordinal=row.ordinal,
        region=Market(country_code="IN", display_name=row.persona[:100]), interests=[], traits=row.traits, evidence_ids=[],
        state=ParticipantState(population_study_id=run.id, stance=_stance_of(row, run.kind), stance_source="interview",  # type: ignore[arg-type]
                               last_round_index=None, interview_id=row.id),
        memories=memories)


def _matches(row: m.PanelParticipant, f: v.SubgroupFilter) -> bool:
    return all(not wanted or have in wanted for wanted, have in (
        (f.states, row.state_code), (f.languages, row.language), (f.city_tiers, row.city_tier), (f.age_bands, row.age_band)))


def _raise_for(exc: LLMError) -> None:
    raise {"PROVIDER_TIMEOUT": ProviderTimeout, "PROVIDER_NOT_CONFIGURED": ProviderNotConfigured}.get(exc.code, ProviderFailed)(exc.message)


async def ask_panel(user_id: UUID, campaign_id: UUID, run_id: UUID, body: v.AskPanelCreate) -> v.PanelQuestion:
    """One question to one participant, a subgroup or the whole panel, answered from each participant's stored response and
    earlier answers. Nothing is invented: a participant with no stored response is not asked."""
    settings = get_settings()
    async with read_session() as s:
        run, project = await _run_in(s, user_id, campaign_id, run_id, ("quick_read", "audience_study"))
        require_writable(project)
        _check_provider(run.mode)
        if run.status not in USABLE:
            raise conflict("run_id", f"The panel has no usable responses yet (status: {run.status}).")
        rows = await _participants(s, run.id)
        target = body.target
        if isinstance(target, v.ParticipantTarget):
            chosen = [r for r in rows if r.id == target.participant_id]
            if not chosen:
                raise not_found("Participant", "target.participant_id")
            target_doc: dict[str, Any] = {"participant_id": str(target.participant_id)}
        elif isinstance(target, v.SubgroupTarget):
            chosen = [r for r in rows if _matches(r, target.filter)]
            if not chosen:
                raise conflict("target.filter", "No participant in this panel matches the filter.")
            target_doc = {"filter": target.filter.model_dump(mode="json", exclude_none=True)}
        else:
            chosen, target_doc = list(rows), {}
        asked = [r for r in chosen if r.response is not None and (run.kind == "quick_read" or r.response.get("status") == "completed")]
        if not asked:
            raise conflict("target", "None of the selected participants has a stored response to answer from.")
        if len(asked) > settings.audience_ask_max_participants:
            raise _invalid("target", f"A question can go to at most {settings.audience_ask_max_participants} participants; narrow the subgroup.")
        history, questions = await _history(s, [r.id for r in asked])
    details = {r.id: _detail(r, run, history.get(r.id, []), questions) for r in asked}
    by_row = {r.id: r for r in asked}
    chunks = [asked[i : i + ASK_BATCH] for i in range(0, len(asked), ASK_BATCH)]
    llm = make_llm(run.mode)
    gate = asyncio.Semaphore(2)

    async def answer(chunk: list[m.PanelParticipant]) -> Any:
        async with gate:
            try:
                if isinstance(target, v.ParticipantTarget):
                    reply = await followup.answer_followup(
                        population_study_id=run.id, participant=details[chunk[0].id], question=body.question, mode=run.mode, llm=llm)
                    return [reply], None, reply.trace
                reply = await followup.answer_group_question(
                    population_study_id=run.id, group_id=target.kind, participants=[details[r.id] for r in chunk],
                    question=body.question, mode=run.mode, llm=llm)
                return reply.answers, reply.summary, reply.trace
            except LLMError as exc:
                return exc

    results = await asyncio.gather(*(answer(c) for c in chunks))
    failures = [r for r in results if isinstance(r, LLMError)]
    if len(failures) == len(results):
        _raise_for(failures[0])
    now = utcnow()
    question_id = uuid4()
    replies, summaries, traces = [], [], []
    for r in results:
        if isinstance(r, LLMError):
            continue
        replies += r[0]
        summaries += [r[1]] if r[1] else []
        traces += [r[2]] if r[2] else []
    answered = {rep.participant_id: rep for rep in replies if rep.participant_id in by_row}
    unanswered = [r.id for r in asked if r.id not in answered]
    limitations = ["Every answer is AI-generated from the participant's stored response and earlier answers; none is a real person.",
                   "A sample of synthetic participants is not the whole market, and agreement between them is not confirmation."]
    if run.mode == "demo":
        limitations.append("Demo mode: answers quote the stored response; no model was called.")
    if unanswered:
        limitations.append(f"{len(unanswered)} selected participant(s) did not get an answer ({'a batch failed' if failures else 'the model omitted them'}).")
    usage = _usage_totals([t for t in traces]).model_dump(mode="json")
    async with session() as s, s.begin():
        s.add(m.PanelQuestion(
            id=question_id, run_id=run.id, asked_by=user_id, target_kind=target.kind, target=target_doc, question=body.question,
            summaries=summaries, stance=stance_distribution(a.stance for a in answered.values()).model_dump(mode="json"),
            unanswered=[str(u) for u in unanswered], mode=run.mode, limitations=limitations, usage=usage, created_at=now))
        await s.flush()
        s.add_all(m.PanelAnswer(
            id=uuid4(), question_id=question_id, run_id=run.id, participant_id=pid, answer=rep.answer, stance=rep.stance,
            memory_refs=[str(x) for x in rep.memory_refs], model_id=rep.model_id, created_at=now) for pid, rep in answered.items())
        for t in traces:
            if _called_model(t):
                await record_ai_usage(AiUsage(
                    capability="text", provider=t.provider or "unknown", model=t.model_id or "unknown", prompt_version=t.prompt_version,
                    input_tokens=(t.usage.input_tokens or 0) if t.usage else 0, output_tokens=(t.usage.output_tokens or 0) if t.usage else 0,
                    estimated_cost_usd=(t.usage.estimated_cost_usd or 0.0) if t.usage else 0.0, latency_ms=t.latency_ms,
                    workspace_id=run.workspace_id, project_id=run.project_id, campaign_id=run.campaign_id, user_id=user_id), s=s)
        await s.flush()
        return await _question_view(s, question_id)


async def _history(s: AsyncSession, participant_ids: list[UUID]) -> tuple[dict[UUID, list[m.PanelAnswer]], dict[UUID, str]]:
    """Each participant's earlier answers, newest first (a bounded window), and the questions they answered."""
    rows = (await s.execute(select(m.PanelAnswer).where(m.PanelAnswer.participant_id.in_(participant_ids))
                            .order_by(m.PanelAnswer.created_at.desc(), m.PanelAnswer.id))).scalars().all()
    grouped: dict[UUID, list[m.PanelAnswer]] = defaultdict(list)
    for a in rows:
        if len(grouped[a.participant_id]) < ASK_HISTORY:
            grouped[a.participant_id].append(a)
    qids = {a.question_id for items in grouped.values() for a in items}
    questions = {q.id: q.question for q in (await s.execute(select(m.PanelQuestion).where(m.PanelQuestion.id.in_(qids)))).scalars()} if qids else {}
    return grouped, questions


async def _question_view(s: AsyncSession, question_id: UUID) -> v.PanelQuestion:
    q = await s.get(m.PanelQuestion, question_id)
    assert q is not None
    run = await s.get(m.AudienceRun, q.run_id)
    assert run is not None
    answers = (await s.execute(select(m.PanelAnswer, m.PanelParticipant).join(
        m.PanelParticipant, m.PanelParticipant.id == m.PanelAnswer.participant_id)
        .where(m.PanelAnswer.question_id == q.id).order_by(m.PanelParticipant.ordinal))).all()
    return v.PanelQuestion(
        id=q.id, run_id=q.run_id, campaign_id=run.campaign_id, target_kind=q.target_kind, target=q.target,  # type: ignore[arg-type]
        question=q.question,
        answers=[v.PanelAnswer(id=a.id, participant_id=a.participant_id, ordinal=p.ordinal, persona=p.persona, question_id=a.question_id,
                               answer=a.answer, stance=a.stance, memory_refs=[UUID(x) for x in a.memory_refs], model_id=a.model_id,  # type: ignore[arg-type]
                               created_at=a.created_at) for a, p in answers],
        stance=q.stance, summaries=list(q.summaries), unanswered_participant_ids=[UUID(x) for x in q.unanswered],  # type: ignore[arg-type]
        mode=q.mode, disclosure=v.PanelDisclosure(), limitations=list(q.limitations),  # type: ignore[arg-type]
        usage=v.UsageTotals.model_validate(q.usage) if q.usage else v.UsageTotals(
            input_tokens=None, output_tokens=None, estimated_cost_usd=None, model_stages=0, cost_note=COST_NOTE),
        asked_by=q.asked_by, created_at=q.created_at)


async def list_questions(
    user_id: UUID, campaign_id: UUID, run_id: UUID, participant_id: UUID | None, limit: int, offset: int
) -> v.PanelQuestionPage:
    async with read_session() as s:
        run, _ = await _run_in(s, user_id, campaign_id, run_id, ("quick_read", "audience_study"))
        stmt = select(m.PanelQuestion).where(m.PanelQuestion.run_id == run.id)
        if participant_id is not None:
            stmt = stmt.where(m.PanelQuestion.id.in_(select(m.PanelAnswer.question_id).where(m.PanelAnswer.participant_id == participant_id)))
        rows, total = await paginate(s, stmt.order_by(m.PanelQuestion.created_at.desc(), m.PanelQuestion.id), limit, offset)
        items = [await _question_view(s, q.id) for q in rows]
    return v.PanelQuestionPage(items=items, limit=limit, offset=offset, total=total)


async def list_participants(user_id: UUID, campaign_id: UUID, run_id: UUID, limit: int, offset: int) -> v.PanelParticipantPage:
    async with read_session() as s:
        run, _ = await _run_in(s, user_id, campaign_id, run_id, ("quick_read", "audience_study"))
        rows, total = await paginate(s, select(m.PanelParticipant).where(m.PanelParticipant.run_id == run.id)
                                     .order_by(m.PanelParticipant.ordinal), limit, offset)
    return v.PanelParticipantPage(items=[v.PanelParticipant(**_participant_base(r)) for r in rows], limit=limit, offset=offset, total=total)


# --- reference ------------------------------------------------------------------------------------------------------


def sampling_options() -> v.SamplingOptions:
    s = get_settings()
    return v.SamplingOptions(
        states=[v.SamplingOption(code=r.code, name=r.name) for r in REGIONS],
        languages=[v.SamplingOption(code=row.code, name=row.name) for row in LANGUAGES],
        city_tiers=list(CITY_TIERS), age_bands=list(AGE_BANDS),  # type: ignore[arg-type]
        protected_traits=sorted(PROTECTED_TRAITS),
        limits={"quick_read_max_participants": s.audience_quick_read_max_participants, "quick_read_min_participants": 6,
                "audience_study_min_participants": 20, "audience_study_max_participants": s.audience_study_max_participants,
                "ask_max_participants": s.audience_ask_max_participants},
        note=SAMPLING_NOTE)
