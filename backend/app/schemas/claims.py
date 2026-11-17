"""Claim drafts: the shared contract between the culture sources (producers) and data-auth (persistence).

Exactly as specified in docs/CONTRACTS_PHASE1.md section 3. Confidence is never set by a source or a model:
`app.analytics.confidence.compute_confidence` derives it from the sources.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

ClaimKind = Literal["observed", "calculated", "synthetic", "interpretation", "unverified"]
ClaimCategory = Literal[
    "language", "script", "festival", "moment", "food", "colour", "symbol",
    "humour", "family", "custom", "sensitivity", "trend", "demographic", "media",
]
ConfidenceLevel = Literal["low", "moderate", "high"]


class ClaimScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country: str = "IN"
    region_code: str | None = None  # IN-XX
    city_tier: str | None = None
    language: str | None = None  # ISO 639-1
    period: str | None = None  # e.g. "2011", "2026-10/2026-11"


class SourceRef(BaseModel):
    source_type: Literal[
        "wikidata", "wikipedia", "wikipedia_pageviews", "holidays_package",
        "census_2011", "curated_reference", "gemini_grounding", "brand_upload",
        "youtube", "gdelt", "google_trends", "reviewer", "campaign_result",
    ]
    source_identifier: str  # Q-id, URL, dataset id, file id
    url: str | None = None
    title: str | None = None
    publisher: str | None = None
    published_at: date | None = None
    retrieved_at: datetime
    excerpt: str | None = None  # exact supporting text when available
    independence_group: str  # sources sharing a group are not independent (e.g. "wikimedia")


class ClaimDraft(BaseModel):
    subject: str  # "region:IN-TN", "entity:Q123", "festival:pongal"
    attribute: str  # snake_case, e.g. "major_festival", "language_share"
    category: ClaimCategory
    value: Any  # JSON-serialisable
    value_text: str  # human-readable statement shown in the UI
    scope: ClaimScope
    kind: ClaimKind
    sources: list[SourceRef]  # may be empty only for kind="interpretation"/"unverified"
    published_at: date | None = None
    retrieved_at: datetime
    expires_at: datetime | None = None
