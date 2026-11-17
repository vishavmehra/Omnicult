"""Curated reference dataset for the four demo states (data/curated/IN-XX.json).

Every entry cites at least one page that was fetched and checked: `scripts/culture_dataset_verify.py` re-fetches each
URL and requires the excerpt to appear verbatim. An entry is `observed` only when its excerpt states the fact;
otherwise it is an `interpretation`. Two sources count as independent only when their `independence_group` differs
(all Wikipedia pages share "wikimedia"). The dataset is a snapshot (`retrieved_on`), not a live feed.
"""

import json
import re
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.culture.base import SourceBase, SourceDescriptor
from app.schemas.claims import ClaimCategory, ClaimDraft, ClaimKind, ClaimScope, SourceRef

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "curated"


class CuratedCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    title: str
    publisher: str
    source_type: Literal["wikipedia", "curated_reference"]
    independence_group: str
    excerpt: str
    published_at: date | None = None


class CuratedEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    category: ClaimCategory
    attribute: str
    subject: str
    value: Any
    value_text: str
    kind: ClaimKind
    language: str | None = None
    period: str | None = None
    sources: list[CuratedCitation] = Field(min_length=1)


class CuratedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_code: str
    dataset_version: str
    retrieved_on: date
    entries: list[CuratedEntry]


@lru_cache(maxsize=8)
def load_curated(region_code: str) -> CuratedFile | None:
    path = DATA_DIR / f"{region_code.upper()}.json"
    if not path.is_file():
        return None
    return CuratedFile.model_validate(json.loads(path.read_text(encoding="utf-8")))


def entry_to_claim(entry: CuratedEntry, region_code: str, retrieved_on: date, *, retrieved_at: datetime | None = None) -> ClaimDraft:
    stamp = retrieved_at or datetime.combine(retrieved_on, time.min, tzinfo=UTC)
    sources = [SourceRef(
        source_type=s.source_type, source_identifier=s.url, url=s.url, title=s.title, publisher=s.publisher,
        published_at=s.published_at, retrieved_at=stamp, excerpt=s.excerpt, independence_group=s.independence_group)
        for s in entry.sources]
    return ClaimDraft(
        subject=entry.subject, attribute=entry.attribute, category=entry.category, value=entry.value,
        value_text=entry.value_text, scope=ClaimScope(region_code=region_code, language=entry.language, period=entry.period),
        kind=entry.kind, sources=sources, retrieved_at=stamp)


def name_variants(name: str) -> set[str]:
    """Lower-cased names a festival goes by: 'Deepavali (Diwali)' -> {'deepavali', 'diwali'}."""
    parts = re.split(r"[()/,]| or ", name.casefold())
    return {" ".join(p.split()) for p in parts if p.strip()}


class CuratedReferenceSource(SourceBase):
    name = "curated"
    descriptor = SourceDescriptor(
        name="curated", source_type="curated_reference",
        supported_operations=frozenset({"related_signals", "moments"}),
        scope="IN-MH, IN-TN, IN-KL, IN-WB: festivals, foods, colours, symbols, moments, customs, sensitivities.",
        coverage_limitations=[
            "A snapshot, not a feed: each entry carries the date its page was read.",
            "Mostly English Wikipedia plus a few government tourism pages; regional-language sources are not yet included.",
            "Excerpts are what the page says, which is not always what a local community would say.",
            "Only the four demo states are covered.",
        ],
        cache_policy={"related_signals": timedelta(days=7), "moments": timedelta(days=7)},
    )

    async def related_signals(self, entity_id: str, *, region_code: str, limit: int = 10) -> list[ClaimDraft]:
        data = load_curated(region_code)
        if data is None:
            return []
        wanted = entity_id.casefold()
        picked = [e for e in data.entries if entity_id.startswith("region:") or e.subject.casefold() == wanted]
        return [entry_to_claim(e, region_code, data.retrieved_on) for e in picked[: max(limit, 0)]]

    async def moments(self, region_code: str, *, year: int) -> list[ClaimDraft]:
        data = load_curated(region_code)
        if data is None:
            return []
        return [entry_to_claim(e, region_code, data.retrieved_on) for e in data.entries if e.category == "moment"]
