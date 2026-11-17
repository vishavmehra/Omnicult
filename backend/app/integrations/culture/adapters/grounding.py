"""Gemini Search grounding as a culture source: cited research, always labelled interpretation.

The model call lives behind the gateway's `grounded_research` capability (built by the gateway stream). This adapter
takes that capability as an injected object (anything with `is_configured()` and `async research(question)` that
returns `.text` and `.citations` with `url`, `title`, `retrieved_at`) and never talks to a provider itself. It is not
configured, and returns nothing, when no capability is injected or the capability reports it is not configured.

A grounded answer is a model summary of web pages, not an official fact: claims are kind "interpretation" and their
sources carry no excerpt, because the cited page was not fetched and quoted here. Without an excerpt a citation does not
count as an observed source in the confidence rules. An answer with no citations is dropped rather than stored.
"""

import re
from datetime import timedelta
from typing import Any, Protocol
from urllib.parse import urlparse

from app.integrations.culture.base import (
    CultureSourceError,
    SourceBase,
    SourceDescriptor,
    SourceHttpError,
    now_utc,
)
from app.integrations.culture.regions import REGIONS
from app.schemas.claims import ClaimDraft, ClaimScope, SourceRef

MAX_TEXT_CHARS = 1_200


class GroundedResearch(Protocol):
    def is_configured(self) -> bool: ...

    async def research(self, question: str, *, stage: str = ..., agent: str = ...) -> Any: ...


def citation_group(url: str, title: str | None) -> str:
    """Independence group for a cited page: Wikimedia pages share one; others are grouped by site.

    Grounding URLs can be redirect links whose title is the site's domain, so the title is preferred when it looks like one."""
    host = (title or "").lower() if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", (title or "").lower()) else (urlparse(url).hostname or "web")
    return "wikimedia" if host.endswith(("wikipedia.org", "wikidata.org", "wikimedia.org")) else f"web:{host}"


class GroundingSource(SourceBase):
    name = "gemini_grounding"
    descriptor = SourceDescriptor(
        name="gemini_grounding", source_type="grounded_llm", supported_operations=frozenset({"related_signals"}),
        scope="Open web through Google Search grounding; any region the question names.",
        coverage_limitations=[
            "A model summary of search results, not an official fact: always an interpretation.",
            "Citations may be redirect links; the cited pages are not fetched or quoted here.",
            "Results vary between runs and over time; each answer records its retrieval time.",
            "Billed per grounded request on top of tokens (see the gateway's price table).",
        ],
        cache_policy={"related_signals": timedelta(days=7)},
        requires_credentials=True,
    )

    def __init__(self, research: GroundedResearch | None = None) -> None:
        self._research = research

    def is_configured(self) -> bool:
        return self._research is not None and self._research.is_configured()

    async def related_signals(self, entity_id: str, *, region_code: str, limit: int = 10) -> list[ClaimDraft]:
        if not self.is_configured() or limit <= 0:
            return []
        region = REGIONS.get(region_code)
        place = region.name if region else region_code
        topic = entity_id.split(":", 1)[1].replace("_", " ") if ":" in entity_id and not entity_id.startswith("region:") else None
        if topic is None and not entity_id.startswith("region:"):
            return []  # a bare id (for example a Wikidata Q-id) has no text to research
        question = (
            f"What do reliable sources say about {topic + ' in ' if topic else 'cultural customs, festivals, foods, colour and symbol associations and sensitivities in '}"
            f"{place}, India, that a consumer brand planning a campaign should know? Cite the sources and say where they are thin or disagree.")
        try:
            answer = await self._research.research(question, stage="culture", agent="grounding")  # type: ignore[union-attr]
        except CultureSourceError:
            raise
        except Exception as exc:  # the gateway raises its own error type; keep its stable code, drop the details
            raise SourceHttpError(self.name, "related_signals", f"grounded research failed ({getattr(exc, 'code', type(exc).__name__)})") from exc
        retrieved = now_utc()
        sources = [SourceRef(
            source_type="gemini_grounding", source_identifier=c.url, url=c.url, title=c.title, retrieved_at=c.retrieved_at or retrieved,
            independence_group=citation_group(c.url, c.title)) for c in answer.citations]
        if not sources or not str(answer.text).strip():
            return []
        text = str(answer.text).strip()
        return [ClaimDraft(
            subject=f"region:{region_code}" if topic is None else entity_id, attribute="grounded_research_summary", category="custom",
            value={"text": text, "question": question},
            value_text=text if len(text) <= MAX_TEXT_CHARS else text[: MAX_TEXT_CHARS - 1] + "…",
            scope=ClaimScope(region_code=region_code), kind="interpretation", sources=sources, retrieved_at=retrieved)]
