"""The ad-code reference index: exact, cited excerpts of the public ASCI (Advertising Standards Council of India) code.

The dataset (`ad_codes_asci.json`) was cut from ASCI's own published PDF; each entry carries its URL and PDF page. Nothing
here is paraphrased or invented, and the index is partial by design: it is reference material for screening a creative,
never legal advice or an ASCI ruling. Risk Check cites entries by id, and code checks every cited id against this index.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel

DATASET = Path(__file__).with_name("ad_codes_asci.json")
Topic = Literal[
    "claims", "substantiation", "misleading", "comparisons", "health_food", "children", "safety", "offence",
    "stereotypes", "disclaimers", "synthetic_media", "green_claims", "pricing_offers", "brand_names",
]


class AdCodeEntry(ApiModel):
    id: str = Field(description="Stable id used by findings, for example asci-1-1.")
    document: str
    document_kind: Literal["code", "guideline"]
    chapter: str
    clause: str = Field(description="Clause number as printed in the document.")
    title: str = Field(description="A short label added by Omnicult for navigation; the excerpt is the ASCI text.")
    topics: list[Topic]
    excerpt: str = Field(description="Exact text from the ASCI document, whitespace-normalised.")
    pdf_page: int = Field(ge=1)
    url: str = Field(description="ASCI's published PDF with a #page fragment.")


class AdCodeSource(ApiModel):
    title: str
    edition: str
    url: str
    also_served_at: str
    landing_page: str
    pages: int
    bytes: int
    sha256: str = Field(description="Hash of the retrieved PDF, so the excerpts can be re-verified against it.")
    note: str


class AdCodeIndex(ApiModel):
    dataset: str
    version: str
    language: str
    retrieved_at: str
    publisher: str
    source: AdCodeSource
    limitations: list[str]
    entries: list[AdCodeEntry]


@lru_cache
def load_index() -> AdCodeIndex:
    return AdCodeIndex.model_validate(json.loads(DATASET.read_text(encoding="utf-8")))


def get_entry(entry_id: str) -> AdCodeEntry | None:
    return next((e for e in load_index().entries if e.id == entry_id), None)


def entries_by_id() -> dict[str, AdCodeEntry]:
    return {e.id: e for e in load_index().entries}
