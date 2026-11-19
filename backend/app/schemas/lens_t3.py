"""Market Lens Tier 3: Trend Radar (feature 12) and Category Shelf (feature 14).

Trend Radar reads public attention (Wikipedia pageviews in the regional language edition) and says in code whether it rose
or fell over named windows. It never speaks of search volume and never of demand. Category Shelf lists the brands and
products Wikidata records in the campaign's category and the state it links them to, with public signals; a field Wikidata
does not hold is absent, never estimated. No model writes any value on either page: counts and statements are observed,
directions and confidence are calculated.

`mode` is the mode of the campaign's brand: demo campaigns read only recorded fixtures, live campaigns only live retrievals.
"""

from datetime import date as Day
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.claims import ConfidenceLevel
from app.schemas.common import ApiModel, DataMode
from app.schemas.lens import LensWindow, RegionCodeStr

TrendDirection = Literal["rising", "falling", "steady", "mixed", "insufficient"]
TermKind = Literal["festival", "category"]
TrendBasis = Literal["regional_edition", "english_only"]
MomentBasis = Literal["public_holiday_list", "source_text", "timing_text"]
MomentsWindowBasis = Literal["campaign_dates", "next_120_days"]
CategoryStatus = Literal["matched", "chosen", "unmatched", "no_category"]
EntityKind = Literal["brand", "product"]


# --- shared ------------------------------------------------------------------------------------------------------


class LensMonth(ApiModel):
    month: str = Field(description="YYYY-MM.")
    views: int
    edition_views: int | None = Field(description="All views of the whole edition that month, when they were read.")
    per_million: float | None = Field(description="Views of the article per million views of the edition: attention as a share of readership.")


class LensSourceLink(ApiModel):
    """Where a number came from. `kind` says how: observed (a count or statement as the source gives it) or calculated."""

    label: str
    url: str | None
    publisher: str
    retrieved_at: datetime
    kind: Literal["observed", "calculated"]


class LensCategoryRef(ApiModel):
    text: str | None = Field(description="The category as the brand kit or the request states it; null when none is stated.")
    pack_key: str | None
    pack_label: str | None
    status: CategoryStatus = Field(
        description="matched: the text names a category pack; chosen: the request named the pack; unmatched: the text names none "
        "(nothing is guessed); no_category: the brand kit states no category."
    )
    note: str | None


class LensCategoryPackOption(ApiModel):
    key: str
    label: str
    topics: list[str] = Field(description="The articles read for attention to the category itself.")


# --- Trend Radar -------------------------------------------------------------------------------------------------


class LensTrendMethod(ApiModel):
    version: str
    measure: str = Field(description="What is counted: Wikipedia pageviews, which is attention to an article.")
    granularity: Literal["monthly"]
    series_months: int = Field(description="Months requested, ending with the last complete month.")
    year_months: int = Field(description="Length of the two windows compared: the last year and the year before it.")
    quarter_months: int = Field(description="Length of the window read beside the label, against the same months a year earlier.")
    change_threshold: float = Field(description="A change of at least this share, up or down, is called rising or falling.")
    min_months: int
    min_views_per_month: int
    description: str


class LensTrendWindows(ApiModel):
    recent_from: str = Field(description="YYYY-MM. The last 12 months.")
    recent_to: str
    prior_from: str = Field(description="The 12 months before them.")
    prior_to: str
    quarter_from: str = Field(description="The last 3 months.")
    quarter_to: str
    quarter_ago_from: str = Field(description="The same 3 months a year earlier.")
    quarter_ago_to: str


class LensTrendEdition(ApiModel):
    language: str
    language_name: str
    project: str
    article: str
    article_url: str
    is_regional: bool = Field(description="The state's own language edition. The English edition is read worldwide, not only in the state.")
    months: int
    total_views: int
    normalised: bool = Field(description="The direction reads attention as a share of the edition's readership. False when its totals were not read.")
    recent_mean: float | None = Field(description="Mean views a month over the last 12 months.")
    prior_mean: float | None = Field(description="Mean views a month over the 12 months before.")
    recent_per_million: float | None
    prior_per_million: float | None
    change: float | None = Field(description="Last 12 months against the 12 before, on the share of readership (raw views when not normalised).")
    raw_change: float | None = Field(description="The same comparison on raw views.")
    edition_change: float | None = Field(description="The whole edition's views, last 12 months against the 12 before.")
    slope_per_month: float | None = Field(description="Least-squares slope through the series, as a share of its mean per month.")
    quarter_change: float | None = Field(description="Last 3 months against the same 3 months a year earlier.")
    direction: TrendDirection
    series: list[LensMonth]


class LensTrendHistoryEntry(ApiModel):
    taken_at: datetime
    direction: TrendDirection
    change: float | None
    last_month: str | None


class LensTrendItem(ApiModel):
    key: str
    term: str
    label: str
    term_kind: TermKind
    festival_subject: str | None
    region_code: str
    region_name: str
    direction: TrendDirection
    change: float | None
    quarter_change: float | None
    confidence: ConfidenceLevel
    confidence_reasons: list[str]
    reasons: list[str] = Field(description="Why the direction is what it is, including why none could be read.")
    basis: TrendBasis
    primary: LensTrendEdition
    reference: LensTrendEdition | None = Field(description="The English edition, shown beside a regional one for context.")
    windows: LensTrendWindows | None
    source: LensSourceLink
    taken_at: datetime
    snapshots: int = Field(description="How many retrievals of this article for this state are kept.")
    history: list[LensTrendHistoryEntry] = Field(description="Earlier retrievals, newest first, read with the same method.")


class LensTrendMoment(ApiModel):
    name: str
    date: Day | None = Field(description="The exact day; null for a festival the sources date only in words (see timing_text).")
    days_until: int | None
    date_basis: MomentBasis
    timing_text: str | None = Field(description="The source's own wording of when, for a moment with no exact date.")
    festival_subject: str | None
    term_key: str | None = Field(description="The radar item reading attention to this moment's festival, when there is one.")
    claim_id: UUID
    source_label: str


class LensTrendRegion(ApiModel):
    region_code: str
    region_name: str
    supported: bool = Field(description="A regional-language Wikipedia edition is mapped for this state.")
    edition_language: str | None
    edition_name: str | None
    items: list[LensTrendItem]
    moments: list[LensTrendMoment]
    gaps: list[str]
    refreshed_at: datetime | None


class LensTrendSummary(ApiModel):
    items: int
    rising: int
    falling: int
    steady: int
    mixed: int
    insufficient: int


class LensTrendRadar(ApiModel):
    campaign_id: UUID
    workspace_id: UUID
    mode: DataMode
    generated_at: datetime
    source_line: str
    category: LensCategoryRef
    method: LensTrendMethod
    summary: LensTrendSummary
    regions: list[LensTrendRegion]
    moments_window: LensWindow
    moments_window_basis: MomentsWindowBasis
    can_refresh: bool
    refreshed_at: datetime | None
    limitations: list[str]


class LensTrendRefreshRequest(ApiModel):
    region_codes: list[RegionCodeStr] | None = Field(
        default=None, max_length=4,
        description="States to refresh (ISO 3166-2:IN). Default: the campaign's states. Live: at most 3 per request.")
    max_terms: Annotated[int, Field(ge=1, le=8)] | None = Field(
        default=None, description="Festival articles per state; the category topics are added. Default from settings.")


# --- Category Shelf ----------------------------------------------------------------------------------------------


class LensShelfAttention(ApiModel):
    """Attention to the entity's Wikipedia article, read the same way as a Trend Radar item."""

    language: str
    language_name: str
    article: str
    article_url: str
    is_regional: bool
    months: int
    total_views: int
    recent_mean: float | None
    change: float | None
    quarter_change: float | None
    normalised: bool
    direction: TrendDirection
    confidence: ConfidenceLevel
    confidence_reasons: list[str]
    series: list[LensMonth]
    source: LensSourceLink


class LensShelfPlace(ApiModel):
    entity_id: str
    label: str


class LensShelfEntity(ApiModel):
    entity_id: str
    label: str
    description: str | None
    kind: EntityKind
    classes: list[str] = Field(description="Wikidata's own words for what the item is an instance of.")
    wikidata_url: str
    website: str | None = Field(description="The official website Wikidata lists. It is a link, never read or scraped.")
    founded_year: int | None
    places: list[LensShelfPlace] = Field(description="Headquarters (brand) or place of location and origin (product), as recorded.")
    basis: str | None = Field(description="How the item was placed in this state, in Wikidata's terms.")
    wikipedia_languages: int = Field(description="Wikipedia language editions with an article about it: public reference, not sales.")
    attention: LensShelfAttention | None
    attention_note: str | None = Field(description="Why attention is not shown, when it is not.")
    sources: list[LensSourceLink]
    unknown: list[str] = Field(description="What Wikidata does not record for this item. Never filled in.")


class LensShelfRegion(ApiModel):
    region_code: str
    region_name: str
    supported: bool
    entities: list[LensShelfEntity]
    gaps: list[str]


class LensShelfExcluded(ApiModel):
    entity_id: str
    label: str
    reason: str
    url: str


class LensShelfSnapshotView(ApiModel):
    id: UUID
    version: int
    taken_at: datetime
    entities: int
    excluded: int


class LensShelf(ApiModel):
    campaign_id: UUID
    workspace_id: UUID
    mode: DataMode
    generated_at: datetime
    source_line: str
    category: LensCategoryRef
    packs: list[LensCategoryPackOption]
    regions: list[LensShelfRegion]
    unplaced: list[LensShelfEntity] = Field(
        description="Brands and products in the category that Wikidata links to no state this product maps, or to a different one.")
    excluded: list[LensShelfExcluded] = Field(description="Candidates read and left out, each with the rule that left it out.")
    ranking: str
    relevance_rule: str
    snapshot: LensShelfSnapshotView | None
    history: list[LensShelfSnapshotView]
    gaps: list[str]
    can_refresh: bool
    limitations: list[str]


class LensShelfRefreshRequest(ApiModel):
    pack_key: str | None = Field(default=None, max_length=60, description="Choose a category pack when the brand kit's category names none.")
    region_codes: list[RegionCodeStr] | None = Field(default=None, max_length=4)


# --- search pulse ----------------------------------------------------------------------------------------------------------


class SearchPulseWeek(ApiModel):
    week: Day = Field(description="The Sunday that starts the week.")
    rank: int | None
    score: int | None = Field(description="Relative interest 0 to 100 in the state that week, as the dataset gives it; null where it gives none.")
    percent_gain: int | None = Field(description="Rising terms only.")


class SearchPulseTerm(ApiModel):
    term: str
    rank: int | None = Field(description="Rank in the dataset's list for the latest week.")
    score: int | None = Field(description="Score in the latest week, as the dataset gives it.")
    percent_gain: int | None = Field(description="Rising terms: the gain the dataset reports.")
    week: Day = Field(description="The latest week in the dataset.")
    weeks_seen: int = Field(description="Weeks, among the ones kept, in which the term has a score.")
    history: list[SearchPulseWeek] = Field(description="Oldest first, one entry per kept week the dataset has a row for.")


class LensSearchPulse(ApiModel):
    campaign_id: UUID
    mode: DataMode
    region_code: str
    region_name: str
    supported: bool = Field(description="False for a state the dataset has no region for (Ladakh, Dadra and Nagar Haveli and Daman and Diu).")
    week: Day | None = Field(description="The latest week.")
    weeks: list[Day] = Field(description="The weeks kept, oldest first.")
    refresh_date: Day | None = Field(description="The dataset partition the rows were read from.")
    retrieved_at: datetime | None
    top: list[SearchPulseTerm]
    rising: list[SearchPulseTerm]
    gaps: list[str]
    can_refresh: bool


class SearchPulseRefresh(ApiModel):
    """What one refresh did. `skipped`: the newest partition was already stored, so no query ran and no bytes were read."""

    refresh_date: Day | None
    skipped: bool
    states: int
    rows: int
    job_id: str | None
    bytes_processed: int | None
