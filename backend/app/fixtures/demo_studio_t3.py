"""Demo-mode "model" output for Claim Guard's optional second pass (Creative Studio, Tier 3).

Hand-written, deterministic and labelled: the gateway records provider "fixture", so a check shows that no model was
called. It covers the fictional Aamod journey only: the second pass notices the delivery promise on the end card ("delivered
home before the festival"), which carries no tell-tale word for the wording rules. Any other creative gets "No demo
fixture for this input" instead of an invented answer, and the rule pass is unaffected.
"""

from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from app.fixtures import demo_aamod

Context = Mapping[str, Any]
SOURCE_PROMISE = "भाऊबीजेपूर्वी घरपोच"
EXPLANATION = (
    "A promise that the order arrives home before the festival day. It may need terms a customer can rely on, such as delivery "
    "areas, an order cut-off and the day it refers to."
)


@lru_cache
def promise_texts() -> frozenset[str]:
    """The delivery promise in every form the journey makes it: the Marathi original, its transcreations, the festival-named chips."""
    copies = {line.copy for line in demo_aamod.PHRASEBOOK[SOURCE_PROMISE].values()}
    chipped = {c[0].replace(c[1], c[2]) for c in demo_aamod.CHIPS.values()}
    return frozenset({SOURCE_PROMISE, *copies, *chipped})


def claim_guard_extract(ctx: Context) -> dict[str, Any] | None:
    rows = ctx["elements"]
    if not any(demo_aamod.TAGLINE in (r.get("text") or "") for r in rows):
        return None  # not the Aamod journey: no fixture, never an invented reading
    promises = promise_texts()
    return {"claims": [
        {"element": r["handle"], "quote": r["text"], "kind": "guarantee", "explanation": EXPLANATION}
        for r in rows if (r.get("text") or "").strip() in promises
    ]}


RESPONDERS = {"claim-guard-extract-v1": claim_guard_extract}
