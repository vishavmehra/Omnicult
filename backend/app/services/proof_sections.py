"""Proof Report sections: a small registry of section providers and the providers wired in this build.

A provider is `async def (ctx: SectionContext) -> Provided | Missing`. `Provided` carries typed content (the model
in `app.schemas.proof` for that section id) and the kind labels saying what in it is observed, calculated, synthetic,
an interpretation, or unverified. `Missing` carries the reason the section cannot be shown. A provider that raises, or
returns content of the wrong type, makes its section `missing`; the report still assembles.

Other streams plug in by replacing a placeholder (every section they own starts as "not available in this build"):

    @provider("risk_findings")
    async def risk(ctx: SectionContext) -> Provided | Missing:
        ...
        return Provided(RiskFindingsContent(...), [KindLabel(kind="calculated", applies_to="...")])

The registry is process-wide; the last registration for an id wins. No provider may call a model: report assembly is
deterministic, and `ctx.now` is the single clock every provider reads.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session
from app.reference import india
from app.schemas import regions as v
from app.schemas.proof import (
    SECTION_MODELS,
    BrandSummary,
    CampaignBriefContent,
    CampaignVersionRef,
    ConflictsContent,
    EvidenceMeterContent,
    KindLabel,
    LimitationsContent,
    RegionClaimsBlock,
    RegionClaimsContent,
    ReportConflict,
    ReportConflictSide,
    RunHistoryContent,
    SectionBase,
    TargetRegionsContent,
)
from app.services import claims as claims_service
from app.services.campaign_regions import campaign_region_codes
from app.services.common import get_owned, require_writable
from app.services.regions import languages_by_region, to_region
from app.services.run_history import load_history

log = logging.getLogger(__name__)

REGISTRY_VERSION = "proof-sections-v1"
NOT_IN_BUILD = "not available in this build"
NO_REGIONS = "No target regions are set for this campaign. Choose regions to report on."
NO_WORKSPACE = "The campaign's project has no workspace, so workspace claims cannot be read."
MAX_CONFLICTS_PER_REGION = 100
MAX_RUNS_IN_REPORT = 100
LEGAL_NOTICE = (
    "This report is an aid to human review. It is not legal advice and it is not legal clearance for any campaign, "
    "claim or creative."
)
KIND_MEANING: dict[str, str] = {
    "observed": "Stated by a cited source and stored with that source, its date and its scope.",
    "calculated": "Computed by fixed rules from stored records. No model decides it.",
    "synthetic": "Produced by the audience panel. Not an independent observation.",
    "interpretation": "A model-generated reading of the evidence: a hypothesis for people to judge, not a fact.",
    "unverified": "A statement with no supporting source yet. Do not rely on it.",
}
KIND_LEGEND = [KindLabel(kind=kind, applies_to=text) for kind, text in KIND_MEANING.items()]  # type: ignore[arg-type]


@dataclass(frozen=True)
class Missing:
    reason: str


@dataclass(frozen=True)
class Provided:
    content: BaseModel
    labels: list[KindLabel]

    def __post_init__(self) -> None:
        if not self.labels:
            raise ValueError("A section must say what kinds of content it holds (kind_labels).")


@dataclass
class SectionContext:
    user_id: UUID
    project: m.Project
    campaign: m.Campaign
    version: m.CampaignVersion
    version_count: int
    brand: m.BrandKit | None
    workspace_id: UUID | None
    mode: str
    now: datetime
    region_source: str
    regions: list[v.Region]
    unknown_codes: list[str]
    results: dict[str, "Provided | Missing"] = field(default_factory=dict)
    _profiles: list[v.RegionProfile] | None = None

    async def profiles(self) -> list[v.RegionProfile]:
        """Region profiles (claims by category plus the Evidence Meter) for the known target regions, read once."""
        if self._profiles is None:
            self._profiles = []
            if self.workspace_id is not None:
                for region in self.regions:
                    self._profiles.append(await claims_service.build_region_profile(
                        self.user_id, self.workspace_id, region.code, mode=self.mode, now=self.now))
        return self._profiles


Provider = Callable[[SectionContext], Awaitable["Provided | Missing"]]


@dataclass(frozen=True)
class SectionSpec:
    id: str
    title: str
    order: int
    provider: Provider
    deferred: bool = False  # runs after the others and may read ctx.results


async def _not_wired(ctx: SectionContext) -> Missing:
    return Missing(NOT_IN_BUILD)


_TABLE = (
    ("campaign_brief", "Campaign brief", 10, False),
    ("target_regions", "Target regions", 20, False),
    ("region_claims", "Regional evidence: claims by category", 30, False),
    ("evidence_meter", "Evidence Meter", 40, False),
    ("conflicts", "Conflicts and decisions", 50, False),
    ("creative_versions", "Creative versions", 60, False),
    ("xray_findings", "Creative X-Ray findings", 70, False),
    ("risk_findings", "Risk flags", 80, False),
    ("transcreation", "Transcreation", 90, False),
    ("audience_results", "Audience results", 100, False),
    ("readiness", "Readiness", 110, False),
    ("approvals", "Human approvals", 120, False),
    ("live_performance", "Actual performance", 130, False),
    ("limitations", "Limitations", 140, True),
    ("run_history", "Run and model metadata", 150, False),
)
REGISTRY: dict[str, SectionSpec] = {i: SectionSpec(i, title, order, _not_wired, deferred) for i, title, order, deferred in _TABLE}
assert set(REGISTRY) == set(SECTION_MODELS)


def provider(section_id: str) -> Callable[[Provider], Provider]:
    """Register (or replace) the provider of a section."""

    def register(fn: Provider) -> Provider:
        REGISTRY[section_id] = replace(REGISTRY[section_id], provider=fn)
        return fn

    return register


def is_wired(spec: SectionSpec) -> bool:
    return spec.provider is not _not_wired


def ordered_specs() -> list[SectionSpec]:
    return sorted(REGISTRY.values(), key=lambda spec: spec.order)


async def build_context(user_id: UUID, campaign_id: UUID, requested: list[str] | None) -> SectionContext:
    """Load what every provider needs, checking that the caller may write to the campaign's project."""
    async with read_session() as s:
        campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign", "campaign_id")
        require_writable(project)
        versions = list((await s.execute(
            select(m.CampaignVersion).where(m.CampaignVersion.campaign_id == campaign.id)
            .order_by(m.CampaignVersion.version_number.desc())
        )).scalars())
        brand = await s.scalar(select(m.BrandKit).where(m.BrandKit.project_id == project.id))
        codes, source = campaign_region_codes(campaign.target_markets, requested)
        rows = list((await s.execute(
            select(m.Region).where(m.Region.code.in_(codes), m.Region.is_active)
        )).scalars()) if codes else []
        languages = await languages_by_region(s, [r.id for r in rows])
    by_code = {r.code: to_region(r, languages[r.id]) for r in rows}
    return SectionContext(
        user_id=user_id, project=project, campaign=campaign, version=versions[0], version_count=len(versions),
        brand=brand, workspace_id=project.workspace_id, mode=project.mode, now=utcnow(), region_source=source,
        regions=[by_code[c] for c in codes if c in by_code], unknown_codes=[c for c in codes if c not in by_code],
    )


async def assemble(ctx: SectionContext) -> list[SectionBase]:
    """Run every registered provider (deferred ones last) and return the sections in report order."""
    specs = ordered_specs()
    sections: dict[str, SectionBase] = {}
    for spec in [s for s in specs if not s.deferred] + [s for s in specs if s.deferred]:
        try:
            result = await spec.provider(ctx)
            ctx.results[spec.id] = result
            sections[spec.id] = _section(spec, result)
        except Exception as exc:  # one section must not take the whole report down; it reports why it is missing
            log.exception("proof section failed", extra={"section": spec.id})
            ctx.results[spec.id] = Missing(f"This section could not be assembled ({type(exc).__name__}).")
            sections[spec.id] = _section(spec, ctx.results[spec.id])
    return [sections[spec.id] for spec in specs]


def _section(spec: SectionSpec, result: "Provided | Missing") -> SectionBase:
    model = SECTION_MODELS[spec.id]
    if isinstance(result, Missing):
        return model(id=spec.id, title=spec.title, status="missing", missing_reason=result.reason, kind_labels=[], content=None)  # type: ignore[call-arg]
    try:
        return model(  # type: ignore[call-arg]
            id=spec.id, title=spec.title, status="available", missing_reason=None, kind_labels=result.labels,
            content=result.content,
        )
    except ValidationError:
        raise TypeError(f"provider of {spec.id} returned content that does not match its schema") from None


# --- providers wired in this build ----------------------------------------------------------------------------


@provider("campaign_brief")
async def campaign_brief(ctx: SectionContext) -> Provided | Missing:
    c, version, brand = ctx.campaign, ctx.version, ctx.brand
    if brand is None:
        return Missing("The campaign's project has no brand kit.")
    return Provided(
        CampaignBriefContent(
            campaign_id=c.id, name=c.name, campaign_type=c.campaign_type, objective=c.objective,  # type: ignore[arg-type]
            target_markets=c.target_markets, evaluation_weights=c.evaluation_criteria,  # type: ignore[arg-type]
            current_version=CampaignVersionRef(
                id=version.id, version_number=version.version_number, content=version.content,  # type: ignore[arg-type]
                created_at=version.created_at),
            version_count=ctx.version_count,
            brand=BrandSummary(
                name=brand.name, description=brand.description, voice=brand.voice, target_audience=brand.target_audience,
                preferred_terms=brand.preferred_terms, prohibited_terms=brand.prohibited_terms,
                protected_terms=brand.protected_terms),
        ),
        [KindLabel(kind="observed", applies_to=(
            "Recorded exactly as the team entered it (the brief, the copy of the current version, the brand kit). "
            "These are the team's own statements and settings, not verified facts about any market."))],
    )


@provider("target_regions")
async def target_regions(ctx: SectionContext) -> Provided | Missing:
    if not ctx.regions:
        return Missing(NO_REGIONS if not ctx.unknown_codes else "None of the requested regions exists: " + ", ".join(ctx.unknown_codes) + ".")
    return Provided(
        TargetRegionsContent(source=ctx.region_source, regions=ctx.regions, unknown_codes=ctx.unknown_codes),  # type: ignore[arg-type]
        [KindLabel(kind="observed", applies_to=f"Region names, codes and official languages come from the curated reference table (India Country Pack v{india.PACK_VERSION}).")],
    )


@provider("region_claims")
async def region_claims(ctx: SectionContext) -> Provided | Missing:
    if ctx.workspace_id is None:
        return Missing(NO_WORKSPACE)
    if not ctx.regions:
        return Missing(NO_REGIONS)
    profiles = await ctx.profiles()
    blocks = [
        RegionClaimsBlock(
            region_code=p.region.code, region_name=p.region.name, claim_count=sum(len(c.claims) for c in p.categories),
            categories=p.categories)
        for p in profiles
    ]
    kinds: dict[str, int] = {}
    for block in blocks:
        for category in block.categories:
            for claim in category.claims:
                kinds[claim.kind] = kinds.get(claim.kind, 0) + 1
    if not kinds:
        return Missing("No claims are recorded for the target regions yet.")
    return Provided(
        RegionClaimsContent(regions=blocks, claim_count=sum(kinds.values()), kind_counts=kinds),
        [KindLabel(kind=k, applies_to=f"{n} claim{'s' if n != 1 else ''}; each shows its own kind, sources, dates, scope and computed confidence.")  # type: ignore[arg-type]
         for k, n in sorted(kinds.items(), key=lambda kv: list(KIND_MEANING).index(kv[0]))],
    )


@provider("evidence_meter")
async def evidence_meter(ctx: SectionContext) -> Provided | Missing:
    if ctx.workspace_id is None:
        return Missing(NO_WORKSPACE)
    if not ctx.regions:
        return Missing(NO_REGIONS)
    return Provided(
        EvidenceMeterContent(meters=[p.meter for p in await ctx.profiles()]),
        [KindLabel(kind="calculated", applies_to=(
            "Counts, freshness, coverage and the strength rating are computed by fixed rules from the stored claims and "
            "sources. A weak region is reported as weak."))],
    )


def _side(claim: v.ClaimView) -> ReportConflictSide:
    return ReportConflictSide(
        claim_id=claim.id, value_text=claim.value_text, kind=claim.kind, confidence=claim.effective_confidence,
        source_count=len(claim.sources))


def _report_conflict(c: v.Conflict) -> ReportConflict:
    return ReportConflict(
        id=c.id, region_code=c.region_code, status=c.status, reason=c.reason, current_selection=c.current_selection,
        selection_reason=c.selection_reason, side_a=_side(c.claim_a), side_b=_side(c.claim_b), decisions=c.resolutions,
        created_at=c.created_at, updated_at=c.updated_at)


@provider("conflicts")
async def conflicts(ctx: SectionContext) -> Provided | Missing:
    if ctx.workspace_id is None:
        return Missing(NO_WORKSPACE)
    if not ctx.regions:
        return Missing(NO_REGIONS)
    found: dict[UUID, ReportConflict] = {}
    truncated = False
    for region in ctx.regions:
        items, total = await claims_service.list_conflicts(
            ctx.user_id, ctx.workspace_id, region_code=region.code, status=None, mode=ctx.mode,
            limit=MAX_CONFLICTS_PER_REGION, offset=0)
        truncated = truncated or total > len(items)
        for item in items:
            found.setdefault(item.id, _report_conflict(item))
    everything = sorted(found.values(), key=lambda c: (c.created_at, str(c.id)))
    labels = [KindLabel(kind="calculated", applies_to=(
        "A conflict is detected by a fixed rule (same subject, attribute and scope, different values). The value in use "
        "is chosen by fixed rules until a reviewer decides."))]
    if any(c.decisions for c in everything):
        labels.append(KindLabel(kind="observed", applies_to="Reviewer decisions are recorded actions with the reviewer and the time."))
    return Provided(
        ConflictsContent(
            open=[c for c in everything if c.status != "resolved"], resolved=[c for c in everything if c.status == "resolved"],
            truncated=truncated),
        labels,
    )


@provider("run_history")
async def run_history(ctx: SectionContext) -> Provided | Missing:
    async with read_session() as s:
        items, totals = await load_history(s, ctx.campaign.id, ctx.workspace_id)
    return Provided(
        RunHistoryContent(totals=totals, runs=items[:MAX_RUNS_IN_REPORT], truncated=len(items) > MAX_RUNS_IN_REPORT),
        [
            KindLabel(kind="observed", applies_to="Models, prompt versions, token counts, statuses, times and errors as recorded for each run."),
            KindLabel(kind="calculated", applies_to=(
                "Durations, totals and costs are calculated from those records. Costs are estimates from a price table, "
                "not provider invoices.")),
        ],
    )


@provider("limitations")
async def limitations(ctx: SectionContext) -> Provided | Missing:
    items = [
        LEGAL_NOTICE,
        "Claims show what their stated sources say. Presence in a source does not establish demand, purchase intent or campaign success.",
    ]
    claims_result = ctx.results.get("region_claims")
    if isinstance(claims_result, Provided):
        counts = claims_result.content.kind_counts  # type: ignore[attr-defined]
        loose = counts.get("interpretation", 0) + counts.get("unverified", 0)
        if loose:
            items.append(f"{loose} claim{'s are' if loose != 1 else ' is'} a model interpretation or unverified, so not a fact.")
    meter_result = ctx.results.get("evidence_meter")
    if isinstance(meter_result, Provided):
        for meter in meter_result.content.meters:  # type: ignore[attr-defined]
            if meter.strength == "weak":
                items.append(f"Evidence for {meter.region_name} ({meter.region_code}) is rated weak: " + " ".join(meter.strength_reasons))
            if meter.stale_claims:
                n = meter.stale_claims
                items.append(f"{n} claim{'s' if n != 1 else ''} for {meter.region_name} {'are' if n != 1 else 'is'} stale or expired.")
    conflict_result = ctx.results.get("conflicts")
    if isinstance(conflict_result, Provided):
        open_count = len(conflict_result.content.open)  # type: ignore[attr-defined]
        if open_count:
            items.append(f"{open_count} conflict{'s are' if open_count != 1 else ' is'} unresolved; the value in use is shown with its reason.")
    history = ctx.results.get("run_history")
    if isinstance(history, Provided) and history.content.totals.runs_without_cost:  # type: ignore[attr-defined]
        items.append("Some runs have no recorded cost, so the estimated total is a lower bound. Costs are estimates, not invoices.")
    items += _record_limitations(ctx)
    if ctx.unknown_codes:
        items.append("Not reported, no such region: " + ", ".join(ctx.unknown_codes) + ".")
    for spec in ordered_specs():
        result = ctx.results.get(spec.id)
        if isinstance(result, Missing):
            items.append(f"{spec.title}: not included ({result.reason}).")
    return Provided(
        LimitationsContent(items=list(dict.fromkeys(items)), not_legal_clearance=LEGAL_NOTICE),
        [KindLabel(kind="calculated", applies_to="Assembled by fixed rules from the other sections. No model wrote these statements.")],
    )



def _record_limitations(ctx: SectionContext) -> list[str]:
    """Limits that come with the sections other streams provide (see `proof_sections_records`): audience results,
    model readings and rule recommendations are named, so a reader cannot take them for more."""
    items: list[str] = []
    found = {section_id: r.content for section_id, r in ctx.results.items() if isinstance(r, Provided)}
    if "audience_results" in found:
        items.append("Audience results share one model's biases and are not independent observations.")
    if "risk_findings" in found:
        items.append("A Risk Check is a screening aid for human review. It is not legal advice, not an ASCI ruling and not clearance, and a creative with no findings has not been cleared.")
    if "xray_findings" in found:
        items.append("Cultural readings in Creative X-Ray are model interpretations, not facts, and a vision or speech model can misread a frame.")
    if "transcreation" in found:
        items.append("Transcreated copy and its back-translation come from one model run and are not reviewed by a native speaker unless a person says so.")
    if "readiness" in found:
        items.append("A readiness verdict is a recommendation computed by fixed rules from the stored observations. It is not an approval and not a forecast.")
    return items


from app.services import proof_sections_records  # noqa: E402,F401  (registers the providers of the other streams' sections)
