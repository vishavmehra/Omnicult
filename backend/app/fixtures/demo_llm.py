"""Demo-mode "model" outputs: one table of fixture responders, keyed by prompt version.

Hand-written, deterministic, and labeled: the gateway records provider "fixture" and the workflows add
"Demo fixture output, not a live model response." Each responder receives the agent's structured input and
returns JSON in that agent's output schema, so validation and cross-reference checks run as in live mode.
The responders live beside their features (`demo_population`, `demo_studio`, `demo_studio_t3`, `demo_aamod`,
`demo_voice`, `pulse_comments`) and are plugged into this table.
"""

from collections.abc import Callable, Mapping
from typing import Any

Context = Mapping[str, Any]
RESPONDERS: dict[str, Callable[[Context], Any]] = {}

from app.fixtures.demo_population import RESPONDERS as POPULATION_RESPONDERS  # noqa: E402

RESPONDERS |= POPULATION_RESPONDERS

from app.fixtures.demo_studio import RESPONDERS as STUDIO_RESPONDERS  # noqa: E402

RESPONDERS |= STUDIO_RESPONDERS

from app.fixtures.demo_studio_t3 import RESPONDERS as STUDIO_T3_RESPONDERS  # noqa: E402

RESPONDERS |= STUDIO_T3_RESPONDERS

from app.fixtures import demo_aamod  # noqa: E402

RESPONDERS |= {"xray-scenes-v1": demo_aamod.xray_scenes}  # the Aamod film only; any other creative gets "no demo fixture"

from app.fixtures.demo_voice import RESPONDERS as VOICE_RESPONDERS  # noqa: E402

RESPONDERS |= VOICE_RESPONDERS
from app.fixtures.pulse_comments import RESPONDERS as PULSE_COMMENT_RESPONDERS  # noqa: E402

RESPONDERS |= PULSE_COMMENT_RESPONDERS  # Comment Pulse reading of the sample comments
