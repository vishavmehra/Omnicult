"""Buzz Simulator (lab-t3): synthetic social reactions to a creative, per region and language.

A seeded synthetic population (the same sampler as every Audience Lab panel) is linked by a seeded "who sees whose posts"
network. A share of it sees the creative first; each account that sees it acts once: it posts, replies, reshares or scrolls
past. A reshare shows the creative to the accounts that follow the sharer, who act in the next round.

The text of each act is the model's. Who saw what, spread, reach per cohort, sentiment counts and message change are
counted by code over the stored acts. Nothing here predicts virality: it is how this synthetic population, with this
network and this exposure setting, passed the creative on.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.audience import (
    AudienceRunMetadata,
    CreativeCopy,
    PanelDescription,
    PanelDisclosure,
    PanelParticipant,
    RegionRef,
    SamplingPlan,
    VersionRef,
)
from app.schemas.campaigns import CampaignContent
from app.schemas.common import ApiModel, DataMode, ShortText
from app.schemas.lab_sessions import BuzzPlatform
from app.schemas.population import ReactionCategory, ReactionDistribution
from app.schemas.runs import RunError, RunProgress, RunStatus

BuzzActionKind = Literal["post", "reply", "share", "ignore"]


class BuzzCreate(ApiModel):
    """Simulate how a creative passes through a synthetic population."""

    sampling: SamplingPlan = Field(description="Name at least one state. Languages, city tiers and age bands default to the states' own.")
    size: int = Field(default=24, ge=12, description="Simulated accounts. The upper bound is a server setting; larger requests get 422.")
    platform: BuzzPlatform = Field(default="instagram", description="Sets the voice and format of the posts only; no platform data is used.")
    rounds: int = Field(default=3, ge=1, description="Rounds of seeing and acting. Each account acts once, in the round after it first sees the creative.")
    initial_exposure: float = Field(default=0.25, ge=0.1, le=0.6, description="Share of the population that sees the creative in round 1. A setting, not a forecast.")
    degree: int = Field(default=4, ge=2, le=6, description="How many other accounts each account sees posts from.")
    content_version_id: UUID | None = Field(default=None, description="Defaults to the campaign's current version.")
    version_ref: VersionRef | None = Field(default=None, description="Opaque reference to a version node; stored, not joined.")
    creative: CampaignContent | None = Field(default=None, description="Copy to simulate instead of a stored version (for example a Studio version).")
    intended_message: ShortText | None = Field(default=None, description="The message the creative should carry; used to see how it changes as it is passed on.")
    seed: int = Field(default=42, ge=0)


class BuzzActView(ApiModel):
    id: UUID
    round_index: int
    participant_id: UUID
    ordinal: int
    state_code: str
    language: str
    language_name: str
    action: BuzzActionKind
    text: str | None = Field(description="What the account wrote, in its own language (it may mix English).")
    text_en: str | None = Field(description="An English gloss of the text, written by the same model.")
    message_gloss: str | None = Field(description="In English: the message this account passes on, as it states it.")
    stance: ReactionCategory
    topics: list[str]
    parent_act_id: UUID | None = Field(description="The post this replies to or reshares; null when it answers the brand's creative itself.")
    exposed_by_participant_id: UUID | None = Field(description="The account whose post showed it the creative; null for the seed audience.")
    wording_overlap: float | None = Field(description="Share of words held in common with the message, 0 to 1. A wording measure, not understanding.")
    changed_message: bool | None = Field(description="True when the shared message shares few words with the reference message.")


class BuzzRoundRow(ApiModel):
    round_index: int
    exposed: int = Field(description="Accounts that saw the creative this round and acted.")
    posts: int
    replies: int
    shares: int
    ignored: int
    newly_exposed: int = Field(description="Accounts shown the creative for the first time by this round's posts and reshares.")
    sentiment: ReactionDistribution = Field(description="Stance of this round's posts, replies and reshares.")


class BuzzCohortRow(ApiModel):
    dimension: Literal["state", "language"]
    value: str
    label: str
    participants: int
    exposed: int
    expressed: int = Field(description="Accounts that posted, replied or reshared.")
    posts: int
    replies: int
    shares: int
    sentiment: ReactionDistribution


class BuzzReach(ApiModel):
    population: int
    seed_exposed: int
    exposed: int = Field(description="Accounts that saw the creative at least once, including the last round's reshares.")
    exposed_share: float
    acted: int
    resharers: int
    cascade_depth: int = Field(description="Longest chain of reshares: 0 when nobody reshared.")
    rounds_run: int
    ended: Literal["rounds_used", "no_new_exposure", "stopped_early"]


class BuzzAmplifier(ApiModel):
    participant_id: UUID
    ordinal: int
    state_code: str
    language_name: str
    exposed_others: int


class BuzzInfluenceEdge(ApiModel):
    from_participant_id: UUID
    to_participant_id: UUID
    round_index: int


class BuzzTheme(ApiModel):
    label: str
    participants: int
    basis: Literal["interpretation"] = "interpretation"


class BuzzMutationExample(ApiModel):
    act_id: UUID
    ordinal: int
    message_gloss: str
    overlap: float


class BuzzMutation(ApiModel):
    reference: str
    reference_source: Literal["intended_message", "creative"]
    compared: int
    changed: int
    threshold: float
    examples: list[BuzzMutationExample]
    note: str


class BuzzConfusion(ApiModel):
    count: int
    act_ids: list[UUID]


class BuzzSummary(ApiModel):
    reach: BuzzReach
    rounds: list[BuzzRoundRow]
    sentiment: ReactionDistribution
    by_state: list[BuzzCohortRow]
    by_language: list[BuzzCohortRow]
    amplifiers: list[BuzzAmplifier]
    influence: list[BuzzInfluenceEdge]
    themes: list[BuzzTheme]
    confusion: BuzzConfusion
    mutation: BuzzMutation
    network_method: str


class BuzzResult(ApiModel):
    id: UUID
    campaign_id: UUID
    project_id: UUID
    status: RunStatus
    mode: DataMode
    platform: BuzzPlatform
    regions: list[RegionRef]
    creative: CreativeCopy
    intended_message: str | None
    initial_exposure: float
    degree: int
    rounds_requested: int
    panel: PanelDescription
    participants: list[PanelParticipant]
    acts: list[BuzzActView]
    summary: BuzzSummary | None
    disclosure: PanelDisclosure
    limitations: list[str]
    error: RunError | None
    progress: RunProgress | None
    run_metadata: AudienceRunMetadata
    created_at: datetime
