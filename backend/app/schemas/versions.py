"""Creative Studio contract: creative elements, the version tree, operations, locks, Tweak Chips, Transcreate and the
Brand Glossary (CONTRACTS_PHASE2 "Shared shapes").

Every operation records who did it (`actor`: user or ai), why, which claims support it, and creates a NEW version node.
The source version is never changed. Confidence and verdicts are never produced here; checks are computed in code.
"""

import json
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.schemas.common import ApiModel, Page

ElementKind = Literal[
    "headline", "body", "cta", "tagline", "logo", "product", "packshot", "image_region", "scene", "voiceover", "music",
    "caption",
]
TEXT_KINDS: frozenset[str] = frozenset({"headline", "body", "cta", "tagline", "voiceover", "caption"})
OperationKind = Literal[
    "manual_edit", "replace_text", "transcreate", "apply_chip", "swap_reference", "change_setting", "tone_shift", "restore",
    "remake",
]
Actor = Literal["user", "ai"]
OperationStatus = Literal["applied", "rejected"]
RejectionCode = Literal["LOCKED", "INVALID", "CHECKS_FAILED"]
ChipOperationType = Literal["replace_text", "swap_reference"]
ChipStatus = Literal["proposed", "applied"]

ElementId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")]
LanguageCode = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}$")]
ScriptCode = Annotated[str, StringConstraints(pattern=r"^[A-Z][a-z]{3}$")]
RegionCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,3}$")]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Dial = Annotated[int, Field(ge=0, le=100)]
MAX_VALUE_CHARS = 20_000  # serialized size of one element value (the engine applies the same bound to edits)


class CreativeElement(ApiModel):
    """One element of a creative: a line of copy, a logo, a scene, a region of an image. `id` is stable across versions."""

    id: ElementId
    kind: ElementKind
    value: Any = Field(default=None, description="Text for copy elements; an asset reference or descriptor otherwise.")
    language: LanguageCode | None = None
    script: ScriptCode | None = None
    bbox: list[Annotated[float, Field(ge=0, le=1)]] | None = Field(
        default=None, min_length=4, max_length=4, description="[x, y, w, h], each normalised to 0-1."
    )
    scene_id: str | None = None
    locked: bool = Field(default=False, description="Whether the element was locked when this version was created.")

    @field_validator("value")
    @classmethod
    def _bounded(cls, value: Any) -> Any:
        if len(json.dumps(value, default=str)) > MAX_VALUE_CHARS:
            raise ValueError(f"An element value may be at most {MAX_VALUE_CHARS} characters.")
        return value


class Tone(ApiModel):
    """Tone Dials. Every dial is 0-100 and changes the parameters passed to generation (see app.studio.checks)."""

    formality: Dial = Field(default=50, description="0 casual, 100 formal.")
    code_mixing: Dial = Field(default=50, description="0 pure language, 100 heavily mixed with English.")
    urban_rural: Dial = Field(default=50, description="0 rural, 100 urban.")
    playfulness: Dial = Field(default=50, description="0 serious, 100 playful.")
    energy: Dial = Field(default=50, description="0 low energy, 100 high energy.")


class VersionSettings(ApiModel):
    tone: Tone | None = None
    generation: dict[str, Any] | None = Field(
        default=None, description="Model metadata of the run that produced this node: run_id, provider, model_id, prompt_version."
    )


class VersionSummary(ApiModel):
    id: UUID
    campaign_id: UUID
    parent_id: UUID | None
    label: str
    created_by: UUID | None
    actor: Actor
    region_code: RegionCode | None
    language: LanguageCode | None
    settings: VersionSettings
    operation_id: UUID | None
    element_count: int
    created_at: datetime


class VersionNode(VersionSummary):
    elements: list[CreativeElement]


class VersionPage(Page[VersionSummary]):
    pass


class VersionCreate(ApiModel):
    """Import an original as a root version. Without `elements` the root is made from the campaign's current copy."""

    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] = "Original"
    elements: list[CreativeElement] | None = Field(default=None, min_length=1, max_length=200)
    region_code: RegionCode | None = None
    language: LanguageCode | None = None
    tone: Tone | None = None

    @model_validator(mode="after")
    def _unique_ids(self) -> "VersionCreate":
        ids = [e.id for e in self.elements or []]
        if len(ids) != len(set(ids)):
            raise ValueError("Element ids must be unique.")
        return self


# --- operations -----------------------------------------------------------------------------


class ElementEdit(ApiModel):
    """Set fields on one element. Only value, language, script, bbox and scene_id can be set."""

    element_id: ElementId
    set: dict[str, Any] = Field(min_length=1)


class ManualEdit(ApiModel):
    kind: Literal["manual_edit", "replace_text"]
    edits: list[ElementEdit] = Field(min_length=1, max_length=50)


class SwapReference(ApiModel):
    kind: Literal["swap_reference"]
    element_id: ElementId
    from_text: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    to_text: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class ChangeSetting(ApiModel):
    kind: Literal["change_setting"]
    region_code: RegionCode | None = None
    language: LanguageCode | None = None

    @model_validator(mode="after")
    def _something(self) -> "ChangeSetting":
        if self.region_code is None and self.language is None:
            raise ValueError("Set region_code, language or both.")
        return self


class ToneShift(ApiModel):
    kind: Literal["tone_shift"]
    tone: Tone


OperationBody = Annotated[ManualEdit | SwapReference | ChangeSetting | ToneShift, Field(discriminator="kind")]


class OperationRequest(ApiModel):
    """Apply one operation to a version. Creates a new version; the source is untouched. A locked element is refused."""

    version_id: UUID
    operation: OperationBody
    reason: Reason
    claim_ids: list[UUID] = Field(default=[], max_length=20, description="Claims that support the change; each must exist.")
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None = None


class Rejection(ApiModel):
    code: RejectionCode
    message: str
    element_ids: list[str] = []


class Operation(ApiModel):
    id: UUID
    campaign_id: UUID
    kind: OperationKind
    source_version_id: UUID
    result_version_id: UUID | None
    target_element_ids: list[str]
    params: dict[str, Any]
    reason: str
    claim_ids: list[UUID]
    actor: Actor
    actor_user_id: UUID | None
    prompt_version: str | None
    estimated_cost_usd: float | None = Field(description="An estimate from the price table; null when unknown or not applicable.")
    status: OperationStatus
    rejection: Rejection | None
    created_at: datetime


class OperationPage(Page[Operation]):
    pass


class OperationResult(ApiModel):
    operation: Operation
    version: VersionNode


class RestoreRequest(ApiModel):
    onto_version_id: UUID | None = Field(
        default=None, description="The version the restore continues from; defaults to the campaign's newest version."
    )
    reason: Reason = "Restored an earlier version."


# --- diff ---------------------------------------------------------------------------------


class FieldChange(ApiModel):
    field: str
    before: Any
    after: Any


class ElementChange(ApiModel):
    element_id: str
    kind: ElementKind
    fields: list[FieldChange]


class VersionDiff(ApiModel):
    """Structured difference from `from_id` to `to_id`. `locked` is not content and is ignored."""

    from_id: UUID
    to_id: UUID
    added: list[CreativeElement]
    removed: list[CreativeElement]
    changed: list[ElementChange]
    preserved: list[str] = Field(description="Ids of elements present in both versions and identical.")
    settings_changes: list[FieldChange]


# --- locks --------------------------------------------------------------------------------


class LockCreate(ApiModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None


class Lock(ApiModel):
    id: UUID
    campaign_id: UUID
    element_id: str
    locked_by: UUID
    reason: str | None
    locked_at: datetime
    released_at: datetime | None
    released_by: UUID | None


class LockPage(Page[Lock]):
    pass


# --- Tweak Chips -------------------------------------------------------------------------------


class ChipGenerate(ApiModel):
    version_id: UUID
    element_id: ElementId
    region_code: RegionCode
    max_chips: int = Field(default=5, ge=1, le=8)


class ChipChange(ApiModel):
    """The proposed change. replace_text: `value`. swap_reference: `from_text` and `to_text`."""

    value: str | None = None
    from_text: str | None = None
    to_text: str | None = None


class Chip(ApiModel):
    id: UUID
    campaign_id: UUID
    version_id: UUID
    element_id: str
    title: str
    operation_type: ChipOperationType
    change: ChipChange
    params: dict[str, Any]
    reason: str
    claim_ids: list[UUID] = Field(description="Supporting claims; every one was supplied to the model and exists.")
    expected_effect: str
    reversible: bool = Field(description="True when the change can be undone by restoring the previous version.")
    estimated_cost_usd: float | None
    status: ChipStatus
    applied_operation_id: UUID | None
    applied_version_id: UUID | None
    prompt_version: str | None
    provider: str | None
    model_id: str | None
    created_at: datetime


class ChipPage(Page[Chip]):
    pass


class ChipsGenerated(ApiModel):
    chips: list[Chip]
    dropped: int = Field(description="Proposals removed in code: unknown or missing claim ids, invalid change, term violation.")
    notes: list[str]


class ChipApply(ApiModel):
    version_id: UUID | None = Field(default=None, description="Defaults to the version the chip was proposed for.")


class ChipApplied(ApiModel):
    chip: Chip
    operation: Operation
    version: VersionNode


# --- Transcreate -----------------------------------------------------------------------------


class TranscreateRequest(ApiModel):
    version_id: UUID | None = Field(
        default=None,
        description="The version to transcreate. Defaults to the newest; pass the original to transcreate again from the source copy.",
    )
    region_code: RegionCode
    language: LanguageCode
    element_ids: list[ElementId] | None = Field(
        default=None, max_length=20, description="Lines to transcreate; default is every unlocked text element."
    )
    tone: Tone = Tone()

    @field_validator("element_ids")
    @classmethod
    def _unique(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("Element ids must be unique.")
        return value


class ScriptCheck(ApiModel):
    """Unicode-block check of the regional copy. `ok` needs the expected script and no letters of another Indic script."""

    expected_script: str
    ok: bool
    dominant_script: str | None
    shares: dict[str, float] = Field(description="Share of letters per script, after removing preserved terms.")
    foreign_scripts: list[str]
    min_share: float
    message: str


class TermChecks(ApiModel):
    """Glossary and brand-kit checks in code, run on BOTH the regional copy and the English back-translation."""

    protected_preserved: bool
    missing_in_copy: list[str]
    missing_in_back_translation: list[str]
    prohibited_in_copy: list[str]
    prohibited_in_back_translation: list[str]
    preferred_translation_missing: list[str]
    preserved_terms: list[str] = Field(description="Protected terms confirmed in the regional copy by code.")


class TranscreatedLine(ApiModel):
    element_id: str
    kind: ElementKind
    source_text: str
    regional_copy: str
    back_translation: str = Field(description="Literal English rendering of the regional copy, by the same model run.")
    explanation: str
    claim_ids: list[UUID]
    reasoning_type: Literal["evidence_supported", "model_interpretation"]
    preserved_terms: list[str]
    script_check: ScriptCheck
    term_checks: TermChecks
    passed: bool = Field(description="False lines are shown for review but were not applied to the new version.")
    problems: list[str]


# --- Brand Glossary --------------------------------------------------------------------------

GlossaryText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
GlossaryLanguage = Annotated[str, StringConstraints(pattern=r"^([a-z]{2,3}|\*)$")]


class GlossaryTermBase(ApiModel):
    term: GlossaryText = Field(description="The original term as written in source copy.")
    language: GlossaryLanguage = Field(default="*", description="Target language (ISO 639-1) this entry applies to, or * for all.")
    script: ScriptCode | None = Field(default=None, description="ISO 15924 script of approved_spelling.")
    approved_spelling: GlossaryText | None = Field(default=None, description="The brand-approved spelling in this language and script.")
    preferred_translation: GlossaryText | None = None
    pronunciation: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    protected: bool = Field(default=False, description="Must survive transcreation (as approved_spelling, else as written).")
    never_translate: bool = Field(default=False, description="Treated like protected: kept as written or as approved_spelling.")
    prohibited_alternatives: list[GlossaryText] = Field(default=[], max_length=20)
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class GlossaryTermCreate(GlossaryTermBase):
    pass


class GlossaryTermUpdate(ApiModel):
    """Partial update; `term` and `language` identify the entry and cannot change."""

    script: ScriptCode | None = None
    approved_spelling: GlossaryText | None = None
    preferred_translation: GlossaryText | None = None
    pronunciation: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    protected: bool | None = None
    never_translate: bool | None = None
    prohibited_alternatives: list[GlossaryText] | None = Field(default=None, max_length=20)
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class GlossaryTerm(GlossaryTermBase):
    id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime


class GlossaryTermPage(Page[GlossaryTerm]):
    pass
