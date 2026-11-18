"""Campaign Desk contract: the versioned Campaign Brief, the Brand Kit, and the Today view.

The Campaign Brief is the one record every workspace reads (regions, languages, channels, budget, dates, success metric).
It is versioned: every change that alters the content adds a new immutable version, and an older version is never edited.
Money and targets are planning inputs. When a brief belongs to a demo project the budget is always labelled `sample`.

The Brand Kit has two parts. The brand record (name, description, voice, term lists) stays in `brand_kits` and is
read here; the design part (logo, colours, fonts per script, product images, never-change zones, tone, tagline, claims
policy) is stored as one validated JSON document. Contrast ratios are calculated in code from the declared colour pairs.

Today is assembled from real rows only; its next actions are rules over those rows, never model output.
"""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.reference.india import REGIONS, SCRIPT_OF
from app.schemas.common import ApiModel, DataMode, Label, MediumText, Page, ShortText, Term

REGION_CODES = frozenset(r.code for r in REGIONS)
SCRIPT_CODES = frozenset(SCRIPT_OF.values())
MONEY_TOLERANCE = 0.005

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_.-]{0,63}$")]
RegionCode = Annotated[str, StringConstraints(pattern=r"^IN-[A-Z]{2}$")]
LanguageCode = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}$")]
ScriptCode = Annotated[str, StringConstraints(pattern=r"^[A-Z][a-z]{3}$")]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
HttpUrl = Annotated[str, StringConstraints(pattern=r"^https?://\S+$", max_length=500)]
# ponytail: shape check only; an unknown IANA name is accepted. Add a zoneinfo lookup if bad zones cause bugs.
Timezone = Annotated[str, StringConstraints(pattern=r"^(UTC|[A-Za-z]+(/[A-Za-z0-9_+-]+){1,2})$")]
HexColour = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]
Money = Annotated[float, Field(ge=0, le=1e12, allow_inf_nan=False)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Path = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200, pattern=r"^[^\\:*?\"<>|\x00-\x1f]+$")]
Bbox = Annotated[list[Annotated[float, Field(ge=0, le=1)]], Field(min_length=4, max_length=4)]

AgeBand = Literal["18-24", "25-34", "35-44", "45-54", "55+"]
CityTier = Literal["tier1", "tier2", "tier3", "rural"]
BriefStatus = Literal["planning", "live", "closed"]
BriefField = Literal[
    "objective", "origin_region", "target_regions", "languages", "channels", "budget", "dates", "success_metric"
]
ContrastGrade = Literal["AAA", "AA", "AA large", "fail"]
TodayWorkspace = Literal["desk", "lens", "studio", "lab", "launch", "pulse", "proof"]
Verdict = Literal["go", "fix", "rethink"]
Actor = Literal["user", "ai", "system"]


class DeskProvenance(ApiModel):
    """Where a record came from: typed by a person, or loaded from a labelled demonstration fixture."""

    source: Literal["user", "demo_fixture"] = "user"
    fixture_id: str | None = None
    fixture_version: int | None = None
    label: str | None = Field(default=None, description="Shown beside the record; a fixture always carries one.")


# --- Campaign Brief ---------------------------------------------------------------------------------------------


class BriefMoney(ApiModel):
    currency: CurrencyCode
    amount: Money


class BriefProduct(ApiModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    description: Text | None = None
    net_weight_g: Annotated[int, Field(ge=1, le=1_000_000)] | None = None
    price: BriefMoney | None = None
    price_note: ShortText | None = None


class BriefAudience(ApiModel):
    summary: Text | None = None
    age_bands: Annotated[list[AgeBand], Field(max_length=5)] = []
    city_tiers: Annotated[list[CityTier], Field(max_length=4)] = []
    targeting_exclusions: Text | None = Field(
        default=None, description="What the audience must never be selected or sampled by (for example protected traits)."
    )


class BriefRegions(ApiModel):
    origin: RegionCode | None = Field(default=None, description="Where the original creative was made (ISO 3166-2:IN).")
    targets: Annotated[list[RegionCode], Field(max_length=36)] = []

    @model_validator(mode="after")
    def _known_and_distinct(self) -> "BriefRegions":
        for code in [*([self.origin] if self.origin else []), *self.targets]:
            if code not in REGION_CODES:
                raise ValueError(f"{code} is not an Indian state or union territory code.")
        if len(set(self.targets)) != len(self.targets):
            raise ValueError("Target regions must be unique.")
        if self.origin and self.origin in self.targets:
            raise ValueError("The origin region is not also a target region.")
        return self


class BriefChannel(ApiModel):
    id: Slug
    name: Label
    format: ShortText | None = None
    creative_ref: Annotated[str, StringConstraints(max_length=120)] | None = Field(
        default=None, description="Opaque reference to the creative this channel runs; shown as text."
    )


class BriefBudget(ApiModel):
    currency: CurrencyCode
    total: Money
    by_region: dict[RegionCode, Money] = {}
    sample: bool = Field(
        default=False,
        description="True when the numbers are planning placeholders. Always true for a demo project (set by the server).",
    )
    note: ShortText | None = None

    @model_validator(mode="after")
    def _allocation_fits(self) -> "BriefBudget":
        if sum(self.by_region.values()) > self.total + MONEY_TOLERANCE:
            raise ValueError("The regional budgets add up to more than the total.")
        return self


class BriefKeyMoment(ApiModel):
    id: Slug
    name: Label
    date: date
    region_codes: Annotated[list[RegionCode], Field(max_length=36)] = []
    source_ids: Annotated[list[Slug], Field(max_length=10)] = []
    note: ShortText | None = None


class BriefDateSource(ApiModel):
    id: Slug
    title: ShortText
    publisher: Label | None = None
    url: HttpUrl | None = None
    retrieved_at: date | None = None


class BriefDates(ApiModel):
    start: date
    end: date
    timezone: Timezone = "Asia/Kolkata"
    key_moments: Annotated[list[BriefKeyMoment], Field(max_length=30)] = []
    sources: Annotated[list[BriefDateSource], Field(max_length=30)] = []
    note: ShortText | None = None

    @model_validator(mode="after")
    def _ordered_and_sourced(self) -> "BriefDates":
        if self.end < self.start:
            raise ValueError("The campaign cannot end before it starts.")
        known = {s.id for s in self.sources}
        if len(known) != len(self.sources):
            raise ValueError("Date source ids must be unique.")
        for moment in self.key_moments:
            missing = [i for i in moment.source_ids if i not in known]
            if missing:
                raise ValueError(f"Key moment {moment.id} cites unknown sources: {', '.join(missing)}.")
        return self


class BriefMetric(ApiModel):
    id: Slug
    definition: ShortText
    target: ShortText | None = None


class BriefSuccessMetric(ApiModel):
    primary: BriefMetric
    secondary: Annotated[list[BriefMetric], Field(max_length=6)] = []
    note: ShortText | None = None


class BriefOriginalCta(ApiModel):
    region_code: RegionCode
    text: ShortText
    translation_en: ShortText | None = None


class BriefCta(ApiModel):
    text_en: ShortText | None = None
    festival_hook: ShortText | None = None
    original: BriefOriginalCta | None = None


class BriefContent(ApiModel):
    """The brief as people write it. Replaced as a whole; each saved change becomes a new version."""

    status: BriefStatus = "planning"
    objective: ShortText | None = None
    product: BriefProduct | None = None
    target_audience: BriefAudience | None = None
    regions: BriefRegions = BriefRegions()
    languages: dict[RegionCode, Annotated[list[LanguageCode], Field(min_length=1, max_length=6)]] = Field(
        default={}, description="Languages per region code (ISO 639-1; ISO 639-3 where no two-letter code exists)."
    )
    scripts: dict[RegionCode, Annotated[list[ScriptCode], Field(min_length=1, max_length=6)]] = Field(
        default={}, description="Scripts per region code (ISO 15924)."
    )
    channels: Annotated[list[BriefChannel], Field(max_length=20)] = []
    budget: BriefBudget | None = None
    dates: BriefDates | None = None
    success_metric: BriefSuccessMetric | None = None
    primary_message: Text | None = None
    cta: BriefCta | None = None
    original_creative_refs: Annotated[list[Annotated[str, StringConstraints(max_length=120)]], Field(max_length=20)] = []
    constraints: Annotated[list[ShortText], Field(max_length=20)] = []

    @model_validator(mode="after")
    def _consistent(self) -> "BriefContent":
        regions = set(self.regions.targets) | ({self.regions.origin} if self.regions.origin else set())
        for label, keyed in (("languages", self.languages), ("scripts", self.scripts)):
            stray = sorted(set(keyed) - regions)
            if stray:
                raise ValueError(f"{label} name regions that are neither the origin nor a target: {', '.join(stray)}.")
        for code, langs in self.languages.items():
            for lang in langs:
                if lang not in SCRIPT_OF:
                    raise ValueError(f"{lang} is not a language in the India reference list.")
                if code in self.scripts and SCRIPT_OF[lang] not in self.scripts[code]:
                    raise ValueError(f"{lang} in {code} is written in {SCRIPT_OF[lang]}, which is not listed for that region.")
        for code, scripts in self.scripts.items():
            for script in scripts:
                if script not in SCRIPT_CODES:
                    raise ValueError(f"{script} is not a script in the India reference list.")
        if len({c.id for c in self.channels}) != len(self.channels):
            raise ValueError("Channel ids must be unique.")
        if self.budget:
            stray = sorted(set(self.budget.by_region) - regions)
            if stray:
                raise ValueError(f"The budget names regions that are neither the origin nor a target: {', '.join(stray)}.")
        if self.dates:
            for moment in self.dates.key_moments:
                stray = sorted(set(moment.region_codes) - regions)
                if stray:
                    raise ValueError(f"Key moment {moment.id} names regions outside the brief: {', '.join(stray)}.")
        if self.success_metric:
            ids = [self.success_metric.primary.id, *[m.id for m in self.success_metric.secondary]]
            if len(set(ids)) != len(ids):
                raise ValueError("Metric ids must be unique.")
        if self.cta and self.cta.original and self.cta.original.region_code not in regions:
            raise ValueError("The original call to action names a region outside the brief.")
        return self


class BriefCompleteness(ApiModel):
    """Calculated from the saved content: which required parts are still empty."""

    complete: bool
    missing: list[BriefField]
    filled: int
    required: int


class BriefUpdate(ApiModel):
    content: BriefContent
    change_note: ShortText | None = Field(default=None, description="Why this version exists; shown in the version list.")
    expected_version: Annotated[int, Field(ge=0)] | None = Field(
        default=None, description="The version the editor was looking at. A different current version is a 409, so edits never overwrite each other."
    )


class CampaignBrief(ApiModel):
    campaign_id: UUID
    project_id: UUID
    version: int = Field(
        ge=0,
        description="0 means no brief has been saved yet; `content` is then derived from the campaign record (objective and regions).",
    )
    saved: bool
    content: BriefContent
    completeness: BriefCompleteness
    change_note: str | None
    created_at: datetime | None
    created_by: UUID | None
    provenance: DeskProvenance
    version_count: int = Field(ge=0)
    mode: DataMode
    editable: bool
    locked_reason: str | None = Field(description="Why the brief cannot be edited here (demo, archived or read-only role).")


class BriefVersionSummary(ApiModel):
    version: int
    created_at: datetime
    created_by: UUID | None
    change_note: str | None
    changed_fields: list[str] = Field(description="Top-level brief fields that differ from the previous version.")
    provenance: DeskProvenance


class BriefVersionPage(Page[BriefVersionSummary]):
    pass


class BriefVersion(ApiModel):
    campaign_id: UUID
    version: int
    content: BriefContent
    change_note: str | None
    created_at: datetime
    created_by: UUID | None
    changed_fields: list[str]
    provenance: DeskProvenance


# --- Brand Kit --------------------------------------------------------------------------------------------------


class KitLockup(ApiModel):
    id: Slug
    use: ShortText
    source_path: Path | None = Field(default=None, description="The raster file (PNG) as named in the source material.")
    vector_path: Path | None = Field(default=None, description="The vector original; reference only, not uploadable here.")
    asset_id: UUID | None = Field(default=None, description="The uploaded asset that holds the raster file, when linked.")


class KitLogo(ApiModel):
    description: Text | None = None
    lockups: Annotated[list[KitLockup], Field(max_length=12)] = []
    clear_space: ShortText | None = None
    min_width_px: dict[Slug, Annotated[int, Field(ge=1, le=10_000)]] = {}
    rules: Annotated[list[ShortText], Field(max_length=20)] = []

    @field_validator("lockups")
    @classmethod
    def _unique(cls, value: list[KitLockup]) -> list[KitLockup]:
        if len({x.id for x in value}) != len(value):
            raise ValueError("Logo lockup ids must be unique.")
        return value


class KitColour(ApiModel):
    id: Slug
    name: Label
    hex: HexColour
    role: ShortText | None = None


class KitContrastPair(ApiModel):
    text: Slug = Field(description="Id of the text colour.")
    background: Slug = Field(description="Id of the background colour.")
    note: ShortText | None = None


class KitFont(ApiModel):
    family: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    weights: Annotated[list[Annotated[int, Field(ge=100, le=900)]], Field(max_length=9)] = []
    scripts: Annotated[list[ScriptCode], Field(min_length=1, max_length=6)]
    role: ShortText | None = None
    license: Label | None = None
    source: HttpUrl | None = None


class KitTone(ApiModel):
    summary: Text | None = None
    traits: Annotated[list[Term], Field(max_length=10)] = []
    do: Annotated[list[ShortText], Field(max_length=20)] = []
    dont: Annotated[list[ShortText], Field(max_length=20)] = []


class KitTagline(ApiModel):
    text: ShortText
    language: LanguageCode | None = None
    script: ScriptCode | None = None
    locked: bool = False
    translate: bool = True
    note: ShortText | None = None


class KitProtectedTerm(ApiModel):
    term: Term
    rule: ShortText | None = None


class KitNeverChange(ApiModel):
    """A zone or element that adaptations must not alter. Locks in Creative Studio enforce it on versions."""

    id: Slug
    description: ShortText
    assets: Annotated[list[Path], Field(max_length=12)] = []
    text: ShortText | None = None
    regions: dict[Slug, Bbox] = Field(default={}, description="Named boxes, normalised [x, y, width, height].")
    bbox_note: ShortText | None = None


class KitProductImage(ApiModel):
    id: Slug
    source_path: Path | None = None
    asset_id: UUID | None = None
    width: Annotated[int, Field(ge=1, le=20_000)] | None = None
    height: Annotated[int, Field(ge=1, le=20_000)] | None = None
    background: Label | None = None
    description: ShortText | None = None
    provenance: ShortText | None = None


class KitClaimsPolicy(ApiModel):
    allowed: Annotated[list[ShortText], Field(max_length=20)] = []
    forbidden: Annotated[list[ShortText], Field(max_length=20)] = []


class KitNameCandidate(ApiModel):
    name: Label
    reason: ShortText


class KitNameCheck(ApiModel):
    checked_at: date | None = None
    method: Text | None = None
    result: Text | None = None
    rejected_candidates: Annotated[list[KitNameCandidate], Field(max_length=10)] = []


class KitDesign(ApiModel):
    """The visual and verbal identity part of the Brand Kit, replaced as a whole."""

    fictional: bool = False
    name_meaning: ShortText | None = None
    category: ShortText | None = None
    name_check: KitNameCheck | None = None
    logo: KitLogo = KitLogo()
    colours: Annotated[list[KitColour], Field(max_length=24)] = []
    contrast_pairs: Annotated[list[KitContrastPair], Field(max_length=40)] = []
    fonts: Annotated[list[KitFont], Field(max_length=24)] = []
    typography_rules: Annotated[list[ShortText], Field(max_length=20)] = []
    tone_of_voice: KitTone = KitTone()
    tagline: KitTagline | None = None
    protected_term_rules: Annotated[list[KitProtectedTerm], Field(max_length=30)] = []
    never_change: Annotated[list[KitNeverChange], Field(max_length=20)] = []
    product_images: Annotated[list[KitProductImage], Field(max_length=20)] = []
    claims_policy: KitClaimsPolicy = KitClaimsPolicy()

    @model_validator(mode="after")
    def _references_resolve(self) -> "KitDesign":
        ids = [c.id for c in self.colours]
        if len(set(ids)) != len(ids):
            raise ValueError("Colour ids must be unique.")
        for pair in self.contrast_pairs:
            for ref in (pair.text, pair.background):
                if ref not in ids:
                    raise ValueError(f"Contrast pair names an unknown colour: {ref}.")
        for label, items in (("never-change zone", self.never_change), ("product image", self.product_images)):
            if len({i.id for i in items}) != len(items):
                raise ValueError(f"Each {label} id must be unique.")
        return self


class KitContrastResult(ApiModel):
    text: Slug
    background: Slug
    text_hex: str
    background_hex: str
    ratio: float = Field(description="WCAG 2.x contrast ratio, calculated from the two colours and rounded to two places.")
    grade: ContrastGrade
    note: str | None


class KitGlossaryLink(ApiModel):
    """The Brand Glossary lives in Creative Studio (`/campaigns/{id}/glossary`); this is its size, for the Brand Kit panel."""

    term_count: int
    protected_count: int
    never_translate_count: int
    languages: list[str]


class KitUpdate(ApiModel):
    design: KitDesign
    expected_revision: Annotated[int, Field(ge=0)] | None = Field(
        default=None, description="The revision the editor was looking at; a different current revision is a 409."
    )


class BrandKit(ApiModel):
    project_id: UUID
    revision: int = Field(ge=0, description="0 means no design has been saved yet.")
    saved: bool
    updated_at: datetime | None
    updated_by: UUID | None
    provenance: DeskProvenance
    # The brand record (edited through PUT /projects/{id}/brand); read here.
    name: str
    description: str | None
    voice: list[str]
    communication_style: str | None
    target_audience: str | None
    preferred_terms: list[str]
    prohibited_terms: list[str]
    protected_terms: list[str]
    design: KitDesign
    contrast: list[KitContrastResult]
    glossary: KitGlossaryLink
    mode: DataMode
    editable: bool
    locked_reason: str | None


# --- Today ------------------------------------------------------------------------------------------------------


class TodayEvent(ApiModel):
    id: str
    at: datetime
    workspace: TodayWorkspace
    kind: str
    title: str
    detail: str | None
    actor: Actor | None
    mode: DataMode
    project_id: UUID
    brand_name: str
    campaign_id: UUID | None
    campaign_name: str | None


class TodayReadiness(ApiModel):
    region_code: str
    region_name: str
    verdict: Verdict
    main_reason: str
    computed_at: datetime
    version_id: UUID
    rule_version: str


class TodayNextAction(ApiModel):
    id: str
    workspace: TodayWorkspace
    title: str
    reason: str
    priority: int = Field(ge=1, le=3, description="1 needs a person soonest.")


class TodayConflict(ApiModel):
    id: UUID
    workspace_id: UUID
    region_code: str | None
    region_name: str | None
    status: Literal["open", "review_requested"]
    reason: str
    claim_a: str
    claim_b: str
    created_at: datetime
    campaign_ids: list[UUID]


class TodayCampaign(ApiModel):
    campaign_id: UUID
    project_id: UUID
    name: str
    brand_name: str
    mode: DataMode
    region_codes: list[str]
    brief_version: int
    brief_complete: bool
    brief_missing: list[BriefField]
    readiness: list[TodayReadiness]
    next_actions: list[TodayNextAction]
    last_activity_at: datetime | None


class TodayView(ApiModel):
    generated_at: datetime
    campaigns: list[TodayCampaign]
    activity: list[TodayEvent] = Field(description="Newest first, from the rows each workspace wrote. Live Pulse writes none.")
    conflicts: list[TodayConflict] = Field(description="Open and review-requested evidence conflicts in the caller's workspaces.")
    limitations: list[str]
