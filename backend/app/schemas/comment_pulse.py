"""Comment Pulse: the labelled sample comments of a campaign, counted and trended by code, read by a model.

Two kinds of content never mix here. Counts, dates, languages and the watch-term matches are computed by code from the
stored comments (`observed` text, `calculated` numbers). A comment's sentiment and the themes are a model interpretation
(live projects) or a labelled fixture reading (demo projects); they live in `CommentAnalysisInfo` and in the fields named
`interpretation` or `sentiment`, so a reader can always tell which is which. Example quotes are stored comments, verbatim.
Every response built from comment data extends `CommentStamp`: `is_sample` is always true.
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import ApiModel, DataMode

SentimentLabel = Literal["positive", "neutral", "negative", "mixed"]
FlagKind = Literal["planted_claim", "cultural_misstep"]
CommentConfidence = Literal["low", "moderate"]
AnalysisStatus = Literal["completed", "partial"]
CommentSort = Literal["likes", "recent"]
FlagFilter = Literal["any", "planted_claim", "cultural_misstep"]


class CommentStamp(ApiModel):
    """Carried by every response that holds comment data, so a view can never lose its label."""

    is_sample: Literal[True] = True
    label: str = Field(description="Always 'Sample comments, not from a connected channel'.")
    source_kind: Literal["sample"] = "sample"
    dataset_version: str
    last_updated_at: datetime = Field(description="When the sample was written (a fixed instant), not when it was loaded.")
    limitations: list[str]


# --- dataset and analysis status -------------------------------------------------------------------------------


class CommentAnalysisInfo(ApiModel):
    """The model reading behind sentiment and themes: who made it, with which prompt, and what code removed."""

    id: UUID
    created_at: datetime
    mode: DataMode
    is_fixture: bool = Field(description="True for a demo project: the reading comes from labelled fixtures, not a model.")
    status: AnalysisStatus
    prompt_version: str
    provider: str
    model_id: str | None
    estimated_cost_usd: float | None
    comment_count: int = Field(description="Comments sent to the reader.")
    read_count: int = Field(description="Comments with a valid label after the code checks.")
    dropped: dict[str, int] = Field(description="What the code checks removed from the output, by reason.")
    notes: list[str]


class CommentDatasetStatus(ApiModel):
    loaded: bool
    is_sample: Literal[True] = True
    label: str
    source_kind: Literal["sample"] = "sample"
    dataset_version: str
    last_updated_at: datetime | None
    comment_count: int
    date_from: date | None
    date_to: date | None
    regions: list[str]
    versions: list[str]
    languages: list[str]
    analysis: CommentAnalysisInfo | None = Field(description="The newest reading of this dataset, or null when none was made.")
    note: str


class CommentReadRequest(ApiModel):
    force: bool = Field(default=False, description="Read again even when the newest reading already covers this dataset.")


class CommentReadResult(ApiModel):
    reused: bool = Field(description="True when the newest reading already covered this dataset and no model was called.")
    analysis: CommentAnalysisInfo


# --- summary: counts and trends by code ---------------------------------------------------------------------------


class CommentFilters(ApiModel):
    region: str | None
    version: str | None
    language: str | None
    date_from: date | None
    date_to: date | None


class SentimentCounts(ApiModel):
    positive: int
    neutral: int
    negative: int
    mixed: int
    unread: int = Field(description="Comments with no model label (no reading yet, or the code removed the label).")


class LanguageCount(ApiModel):
    language: str
    language_name: str
    script: str
    comments: int
    code_mixed_comments: int


class CommentSlice(ApiModel):
    """One region and version: the unit a reader compares."""

    region_code: str
    region_name: str
    version_label: str
    comments: int
    likes: int
    claim_mentions: int
    cultural_mentions: int
    sentiment: SentimentCounts | None
    positive_share: float | None = Field(description="Of the comments read, from the model labels. Null with no reading.")
    negative_share: float | None
    confidence: CommentConfidence = Field(description="By code: Low under 8 comments read or no reading, else Moderate. Never above Moderate: sample comments.")
    confidence_rule: str


class DayCount(ApiModel):
    date: date
    comments: int


class WeekTrend(ApiModel):
    week_start: date
    week_end: date
    comments: int
    claim_mentions: int
    cultural_mentions: int
    read: int
    negative_share: float | None


class CommentCoverage(ApiModel):
    comments_in_dataset: int
    comments_in_view: int
    read_in_view: int
    read_share: float | None = Field(description="Share of the comments in view that carry a model label; null with no reading.")
    languages_in_view: int


class CommentTotals(ApiModel):
    comments: int
    likes: int
    claim_mentions: int
    cultural_mentions: int
    flagged_comments: int


class CommentSummary(CommentStamp):
    filters: CommentFilters
    coverage: CommentCoverage
    totals: CommentTotals
    sentiment: SentimentCounts | None
    analysis: CommentAnalysisInfo | None
    slices: list[CommentSlice]
    languages: list[LanguageCount]
    daily: list[DayCount]
    weekly: list[WeekTrend]


# --- themes (model interpretation) --------------------------------------------------------------------------------


class CommentQuote(ApiModel):
    """A stored comment, verbatim. Code picks it (most liked first); a model never writes a quote."""

    id: UUID
    ref: str
    text: str
    language: str
    region_code: str
    version_label: str
    likes: int
    sentiment: SentimentLabel | None


class ThemeBreakdown(ApiModel):
    key: str
    comments: int


class CommentTheme(ApiModel):
    id: str
    label: str = Field(description="Model interpretation.")
    summary: str = Field(description="Model interpretation.")
    comments: int = Field(description="Comments carrying this theme in view, counted by code from the labels.")
    share_of_read: float
    sentiment: SentimentCounts
    regions: list[ThemeBreakdown]
    versions: list[ThemeBreakdown]
    quotes: list[CommentQuote]


class CommentThemes(CommentStamp):
    filters: CommentFilters
    analysis: CommentAnalysisInfo | None
    themes: list[CommentTheme]
    unthemed: int = Field(description="Read comments in view that carry no theme.")


# --- comments ---------------------------------------------------------------------------------------------------


class CommentFlag(ApiModel):
    """A watch-term match, found by code in the comment text. The match is observed; what it means is the note."""

    kind: FlagKind
    watch_id: str
    label: str
    matched_term: str
    note: str
    evidence: Literal["observed"] = "observed"


class VersionAnchor(ApiModel):
    """Where a comment belongs: the Live Pulse version and region it was posted under, and the closest Creative Studio version."""

    version_label: str
    region_code: str
    region_name: str
    studio_version_id: UUID | None
    studio_version_label: str | None


class CommentThemeRef(ApiModel):
    id: str
    label: str


class CommentInterpretation(ApiModel):
    """The model reading of one comment."""

    sentiment: SentimentLabel
    themes: list[CommentThemeRef]


class CommentItem(ApiModel):
    id: UUID
    ref: str
    day: date
    platform: str
    region_code: str
    region_name: str
    language: str
    language_name: str
    script: str
    code_mixed: bool
    version_label: str
    text: str
    likes: int
    anchor: VersionAnchor
    flags: list[CommentFlag]
    interpretation: CommentInterpretation | None


class CommentPage(CommentStamp):
    items: list[CommentItem]
    total: int
    limit: int
    offset: int
