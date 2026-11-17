"""Regions, region evidence profiles, the Evidence Meter, and evidence conflicts (Omnicult).

Every claim is shown with its five tags: source (`sources`), date (`published_at`, `retrieved_at`), kind, scope and
confidence. `confidence` is computed by the server from the sources; `effective_confidence` is one level lower while the
claim sits in an unresolved conflict (handoff 6.3).
"""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.claims import ClaimCategory, ClaimKind, ClaimScope, ConfidenceLevel
from app.schemas.common import ApiModel, Page

RegionKind = Literal["state", "union_territory"]
LanguageRole = Literal["primary", "secondary", "code_mixed"]
ClaimStatus = Literal["active", "needs_review", "rejected", "superseded"]
ConflictStatus = Literal["open", "review_requested", "resolved"]
ConflictDecision = Literal["accept", "switch", "request_review"]
EvidenceStrength = Literal["weak", "partial", "solid"]
DataMode = Literal["live", "demo"]


class RegionLanguage(ApiModel):
    code: str = Field(description="ISO 639-1; ISO 639-3 where no two-letter code exists.")
    name: str
    native_name: str | None
    script: str = Field(description="ISO 15924.")
    role: LanguageRole = Field(
        description="primary: principal official language; secondary: additional official or widely used. Not a speaker share."
    )


class Region(ApiModel):
    id: UUID
    code: str = Field(description="ISO 3166-2, for example IN-TN.")
    name: str
    country_code: str
    kind: RegionKind
    primary_language: str | None = Field(description="Language code of the principal official language.")
    primary_script: str | None
    languages: list[RegionLanguage]


class RegionPage(Page[Region]):
    pass


class SourceView(ApiModel):
    id: UUID
    source_type: str
    source_identifier: str
    url: str | None
    title: str | None
    publisher: str | None
    published_at: date | None
    retrieved_at: datetime
    excerpt: str | None
    independence_group: str


class ClaimView(ApiModel):
    id: UUID
    shared: bool = Field(description="True for shared reference claims; false for claims owned by the workspace.")
    subject: str
    attribute: str
    category: ClaimCategory
    value: Any = Field(description="The JSON value; `value_text` is the statement to show people.")
    value_text: str
    scope: ClaimScope
    kind: ClaimKind
    confidence: ConfidenceLevel = Field(description="Computed from the sources by the server; never set by a source or a model.")
    effective_confidence: ConfidenceLevel = Field(description="One level lower than `confidence` while the claim is in an open conflict.")
    confidence_reason: str
    sources: list[SourceView]
    published_at: date | None
    retrieved_at: datetime
    expires_at: datetime | None
    status: ClaimStatus
    stale: bool = Field(description="No observed source is under two years old, or the claim has expired.")
    conflict_ids: list[UUID] = Field(description="Unresolved conflicts this claim is part of.")


class CategoryClaims(ApiModel):
    category: ClaimCategory
    claims: list[ClaimView] = Field(description="Empty when the region has no claim in this category: a visible gap.")


class CategoryCoverage(ApiModel):
    category: ClaimCategory
    claims: int
    supported_claims: int


class SourceFreshness(ApiModel):
    newest_source_date: date | None
    oldest_source_date: date | None
    median_age_days: int | None
    fresh_source_share: float | None = Field(description="Share of sources under two years old (0 to 1); null without sources.")


class ConfidenceBreakdown(ApiModel):
    low: int
    moderate: int
    high: int


class EvidenceMeter(ApiModel):
    """How well-evidenced a region is. A weak region is reported as weak, whatever the profile looks like."""

    region_code: str
    region_name: str
    workspace_id: UUID
    mode: DataMode
    sources: int = Field(description="Distinct sources across the region's claims.")
    claims: int
    supported_claims: int = Field(description="Observed or calculated claims backed by at least one observed source.")
    freshness: SourceFreshness
    categories_total: int
    categories_covered: int = Field(description="Categories with at least one supported claim.")
    coverage: list[CategoryCoverage]
    open_conflicts: int
    stale_claims: int
    needs_review_claims: int = Field(
        description="Claims flagged for review, model interpretations and unverified statements, and claims in a conflict marked for review."
    )
    confidence: ConfidenceBreakdown
    strength: EvidenceStrength
    strength_reasons: list[str] = Field(description="Why the region is not rated solid; empty only for solid.")


class RegionProfile(ApiModel):
    region: Region
    workspace_id: UUID
    mode: DataMode
    meter: EvidenceMeter
    categories: list[CategoryClaims]


class ConflictResolutionView(ApiModel):
    id: UUID
    decision: ConflictDecision
    selection_after: Literal["a", "b"]
    note: str | None
    decided_by: UUID
    decided_at: datetime


class Conflict(ApiModel):
    """Two claims about the same subject, attribute and scope with different values. Both are kept and shown."""

    id: UUID
    workspace_id: UUID
    region_code: str | None
    status: ConflictStatus
    reason: str
    current_selection: Literal["a", "b"] = Field(description="Which value is used while the conflict stands, and after a decision.")
    selection_reason: str = Field(description="Why that value is used.")
    claim_a: ClaimView
    claim_b: ClaimView
    resolutions: list[ConflictResolutionView] = Field(description="Decisions so far, oldest first.")
    created_at: datetime
    updated_at: datetime


class ConflictPage(Page[Conflict]):
    pass


class ConflictResolveRequest(ApiModel):
    decision: ConflictDecision = Field(
        description="accept: keep the value in use; switch: use the other value; request_review: ask for a native review."
    )
    note: str | None = Field(default=None, max_length=1000)
