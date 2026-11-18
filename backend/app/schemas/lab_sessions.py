"""Audience Lab sessions (lab-t3): what the Focus Group, Buzz and Message Check forms need before a run starts.

Defaults come from the server so the screen and the validators cannot drift apart: the default moderator guide, the
platforms Buzz can voice, the brief's primary message (the thing Message Check compares against) and the limits.
"""

from typing import Literal

from app.schemas.common import ApiModel

BuzzPlatform = Literal["instagram", "facebook", "youtube", "x", "whatsapp"]


class LabPlatformOption(ApiModel):
    value: BuzzPlatform
    label: str


class LabSessionLimits(ApiModel):
    focus_min_speakers: int
    focus_max_speakers: int
    focus_max_guide_questions: int
    focus_max_interjections: int
    buzz_min_participants: int
    buzz_max_participants: int
    buzz_max_rounds: int
    message_check_min_per_region: int
    message_check_max_per_region: int
    message_check_max_regions: int
    message_check_max_key_points: int


class LabSessionDefaults(ApiModel):
    guide: list[str]
    platforms: list[LabPlatformOption]
    primary_message: str | None
    primary_message_source: Literal["brief"] | None
    key_points: list[str]
    limits: LabSessionLimits
