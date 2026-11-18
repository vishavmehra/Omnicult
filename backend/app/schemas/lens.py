"""Market Lens: building region profiles from the culture sources and reading them as an atlas, a state profile, a
side-by-side comparison, a moment calendar and a language map.

Every fact is a claim (`ClaimView`, from the regions contract) with its five tags. Nothing here computes confidence:
it comes from the claims. `mode` is the mode of the campaign's brand: demo campaigns read only labelled fixture claims,
live campaigns read only live claims, and the two are never mixed.
"""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.claims import ClaimKind, ConfidenceLevel
from app.schemas.common import ApiModel, DataMode, Page
from app.schemas.regions import ClaimView, Conflict, EvidenceMeter, EvidenceStrength, LanguageRole, Region, RegionKind

RegionCodeStr = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$")]
BuildStatus = Literal["completed", "partial", "failed"]
CallStatus = Literal["ok", "empty", "error"]
DatePrecision = Literal["day", "text"]
DateBasis = Literal["public_holiday_list", "source_text"]


# --- builds ------------------------------------------------------------------------------------------------------


class LensBuildRequest(ApiModel):
    region_codes: list[RegionCodeStr] = Field(
        min_length=1, max_length=36, description="States and union territories to build (ISO 3166-2:IN). Live builds take at most 6 per request."
    )
    years: list[Annotated[int, Field(ge=2000, le=2100)]] | None = Field(
        default=None, max_length=3, description="Calendar years whose public holidays are gathered. Default: this year and the next."
    )
    include_trends: bool = Field(default=True, description="Read Wikipedia pageviews for the festivals cited (live: network calls; labelled attention, not demand).")
    include_grounding: bool = Field(
        default=False, description="Live only. Add one Gemini Google-Search grounded research answer per region (costs credit; always an interpretation)."
    )


class LensCallView(ApiModel):
    source: str
    operation: str
    status: CallStatus
    cached: bool
    result_count: int
    duration_ms: int
    error_type: str | None = Field(description="timeout, network, rate_limited, http, auth, validation, not_configured or an adapter error name.")
    error: str | None
    retrieved_at: datetime


class LensBuildView(ApiModel):
    """One saved, versioned build of a region profile. `version` counts builds per workspace, region and mode."""

    id: UUID
    campaign_id: UUID
    workspace_id: UUID
    region_code: str
    region_name: str
    mode: DataMode
    version: int
    status: BuildStatus = Field(description="completed: every source answered; partial: some failed or are not configured; failed: nothing stored.")
    years: list[int]
    include_trends: bool
    include_grounding: bool
    claim_count: int = Field(description="Claims this build gathered (after merging equal statements).")
    created_claims: int
    updated_claims: int = Field(description="Claims already stored that gained a source or a newer retrieval date.")
    conflicts_opened: int
    rejected_claims: int
    categories: dict[str, int]
    gaps: list[str] = Field(description="What is missing: empty categories, failed sources, sources that are not configured.")
    sources_skipped: list[str]
    error: str | None
    started_at: datetime
    finished_at: datetime
    calls: list[LensCallView] = Field(description="The source calls of this build; empty in build lists.")


class LensBuildBatch(ApiModel):
    builds: list[LensBuildView]


class LensBuildPage(Page[LensBuildView]):
    pass


# --- shared ------------------------------------------------------------------------------------------------------


class LensSourceSummary(ApiModel):
    """A source family behind the claims on a page, with its dates and its limits, so every page states what it rests on."""

    source_type: str
    label: str
    description: str
    claims: int
    sources: int = Field(description="Distinct sources (pages, tables, packages) cited.")
    newest_published_at: date | None
    oldest_published_at: date | None
    newest_retrieved_at: datetime | None
    limitations: list[str]


# --- atlas -------------------------------------------------------------------------------------------------------


class LensAtlasState(ApiModel):
    code: str
    name: str
    kind: RegionKind
    primary_language: str | None
    primary_script: str | None
    strength: EvidenceStrength
    strength_reasons: list[str]
    claims: int
    supported_claims: int
    categories_covered: int
    categories_total: int
    missing_categories: list[str]
    sources: int
    source_types: list[str]
    newest_source_date: date | None
    open_conflicts: int
    stale_claims: int
    built: bool = Field(description="A profile build exists for this state in this mode.")
    last_build: LensBuildView | None


class LensAtlasSummary(ApiModel):
    states_total: int
    states_with_claims: int
    weak: int
    partial: int
    solid: int
    claims: int
    open_conflicts: int


class LensAtlas(ApiModel):
    campaign_id: UUID
    workspace_id: UUID
    mode: DataMode
    mode_label: str
    generated_at: datetime
    summary: LensAtlasSummary
    states: list[LensAtlasState] = Field(description="Every state and union territory, evidence strength included even when weak or empty.")
    sources: list[LensSourceSummary]
    limitations: list[str]


# --- state profile -----------------------------------------------------------------------------------------------


class LensElsewhere(ApiModel):
    view: Literal["calendar", "language_map"]
    label: str
    claims: int


class LensProfileSection(ApiModel):
    key: Literal["languages", "festivals", "references", "tone", "trends"]
    title: str
    description: str
    categories: list[str]
    claims: list[ClaimView]
    elsewhere: list[LensElsewhere] = Field(description="Claims of these categories that are shown in another Lens view instead.")
    empty_reason: str | None = Field(description="Why the section is empty; null when it has claims.")


class LensStateProfile(ApiModel):
    campaign_id: UUID
    workspace_id: UUID
    mode: DataMode
    mode_label: str
    generated_at: datetime
    region: Region
    meter: EvidenceMeter
    sections: list[LensProfileSection]
    conflicts: list[Conflict]
    build: LensBuildView | None = Field(description="The latest build; null when the state has never been built in this mode.")
    sources: list[LensSourceSummary]
    gaps: list[str]
    limitations: list[str]


# --- compare -----------------------------------------------------------------------------------------------------


class LensCompareItem(ApiModel):
    label: str
    subject: str
    attribute: str
    claim_id: UUID
    kind: ClaimKind
    confidence: ConfidenceLevel = Field(description="Effective confidence: one level lower while the claim is in an open conflict.")
    source_count: int
    newest_source_date: date | None
    stale: bool
    in_conflict: bool
    also_in: list[str] = Field(description="Other compared states with a sourced claim on the same subject. Absence elsewhere means no claim was found, not that the thing does not exist.")


class LensCompareCell(ApiModel):
    region_code: str
    total: int = Field(description="Claims in this cell before the display limit.")
    items: list[LensCompareItem]
    missing: bool = Field(description="No claim in this dimension for this state: a gap in the evidence, not a statement about the state.")


class LensCompareRow(ApiModel):
    key: str
    title: str
    categories: list[str]
    cells: list[LensCompareCell]
    shared_subjects: int = Field(description="Subjects with a sourced claim in every compared state.")


class LensCompareRegion(ApiModel):
    region: Region
    strength: EvidenceStrength
    strength_reasons: list[str]
    claims: int
    supported_claims: int
    categories_covered: int
    categories_total: int
    missing_categories: list[str]
    sources: int
    newest_source_date: date | None
    open_conflicts: int
    stale_claims: int
    low: int
    moderate: int
    high: int
    built: bool


class LensCompare(ApiModel):
    campaign_id: UUID
    workspace_id: UUID
    mode: DataMode
    mode_label: str
    generated_at: datetime
    regions: list[LensCompareRegion]
    rows: list[LensCompareRow]
    sources: list[LensSourceSummary]
    limitations: list[str]


# --- moment calendar ---------------------------------------------------------------------------------------------


class LensDatedMoment(ApiModel):
    """A moment with an exact date for the selected year: a claim whose value carries the date."""

    key: str
    name: str
    subject: str
    date: date
    date_basis: DateBasis
    festival_subject: str | None = Field(description="The festival entry this date corresponds to, when the source list links them.")
    in_window: bool | None = Field(description="Inside the requested campaign window; null when no window was requested.")
    claim: ClaimView
    also_stated_by: list[ClaimView] = Field(description="Other claims that give the same date for the same subject (a second source that agrees).")


class LensTiming(ApiModel):
    text: str = Field(description="The timing exactly as the source states it.")
    attribute: str
    claim: ClaimView


class LensTimedMoment(ApiModel):
    """A festival or moment a source describes without an exact date for the year. Months named are read from the text."""

    subject: str
    name: str
    timings: list[LensTiming]
    months_named: list[int]
    dated_for_year: list[date] = Field(description="Exact dates of linked public-holiday entries in the selected year.")
    may_overlap_window: bool | None = Field(description="A month named in the timing text falls inside the requested window; null without a window.")
    conflict_ids: list[UUID]


class LensCalendarMonth(ApiModel):
    month: int
    name: str
    dated: list[LensDatedMoment]


class LensWindow(ApiModel):
    date_from: date
    date_to: date


class LensCalendar(ApiModel):
    campaign_id: UUID
    workspace_id: UUID
    mode: DataMode
    mode_label: str
    generated_at: datetime
    region: Region
    year: int
    years_available: list[int] = Field(description="Years with stored public-holiday dates for this state. Other years need a build that includes them.")
    window: LensWindow | None
    months: list[LensCalendarMonth]
    timed: list[LensTimedMoment]
    conflicts: list[Conflict]
    sources: list[LensSourceSummary]
    gaps: list[str]
    limitations: list[str]


# --- language map ------------------------------------------------------------------------------------------------


class LensShare(ApiModel):
    percent: float
    speakers: int | None
    claim: ClaimView = Field(description="The calculated share claim, with its sources.")


class LensLanguageEntry(ApiModel):
    code: str | None
    name: str
    native_name: str | None
    script: str | None
    role: LanguageRole | None = Field(description="From the reference table (principal or additional official language); not a speaker share. Null for census-only languages.")
    shares: list[LensShare] = Field(description="Census 2011 mother-tongue shares. More than one value means sources disagree; all are kept.")
    disputed: bool


class LensLanguageRegion(ApiModel):
    region_code: str
    region_name: str
    primary_language: str | None
    primary_script: str | None
    has_census: bool
    languages: list[LensLanguageEntry]
    conflicts: list[Conflict] = Field(description="Conflicts between share claims of this state; both values stay in `shares`.")


class LensCodeMixing(ApiModel):
    status: Literal["no_sourced_claims"]
    note: str


class LensLanguageMap(ApiModel):
    campaign_id: UUID
    workspace_id: UUID
    mode: DataMode
    mode_label: str
    generated_at: datetime
    period: str = Field(description="The census year the shares describe.")
    regions: list[LensLanguageRegion]
    code_mixing: LensCodeMixing
    sources: list[LensSourceSummary]
    limitations: list[str]
