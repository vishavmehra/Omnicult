"""Gemini grounding adapter: injected capability, interpretation claims, citations as sources, nothing when unconfigured."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.integrations.culture.adapters.grounding import GroundingSource, citation_group
from app.integrations.culture.base import SourceHttpError

STAMP = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)


class FakeResearch:
    def __init__(self, configured: bool = True, citations=None, text: str = "Pongal is widely celebrated in January.") -> None:
        self.configured, self.questions, self.error = configured, [], None
        self.citations = citations if citations is not None else [
            SimpleNamespace(url="https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc", title="en.wikipedia.org", retrieved_at=STAMP),
            SimpleNamespace(url="https://www.example.org/pongal", title="example.org", retrieved_at=STAMP)]
        self.text = text

    def is_configured(self) -> bool:
        return self.configured

    async def research(self, question: str, *, stage: str = "", agent: str = ""):
        self.questions.append(question)
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text, citations=self.citations)


async def test_returns_nothing_when_not_configured():
    assert not GroundingSource().is_configured() and await GroundingSource().related_signals("region:IN-TN", region_code="IN-TN") == []
    off = FakeResearch(configured=False)
    assert not GroundingSource(off).is_configured()
    assert await GroundingSource(off).related_signals("region:IN-TN", region_code="IN-TN") == [] and off.questions == []


async def test_grounded_answer_is_an_interpretation_with_citation_sources():
    research = FakeResearch()
    (claim,) = await GroundingSource(research).related_signals("region:IN-TN", region_code="IN-TN")
    assert "Tamil Nadu" in research.questions[0]
    assert claim.kind == "interpretation" and claim.category == "custom" and claim.scope.region_code == "IN-TN"
    assert claim.value["text"] == research.text and claim.value_text == research.text
    assert [s.source_type for s in claim.sources] == ["gemini_grounding"] * 2
    assert all(s.excerpt is None for s in claim.sources)  # the cited pages were not fetched and quoted: not observed
    assert [s.independence_group for s in claim.sources] == ["wikimedia", "web:example.org"]
    assert claim.sources[0].retrieved_at == STAMP and claim.sources[0].url.startswith("https://vertexaisearch")


async def test_an_answer_without_citations_is_dropped():
    assert await GroundingSource(FakeResearch(citations=[])).related_signals("region:IN-TN", region_code="IN-TN") == []


async def test_a_bare_id_has_nothing_to_research_and_costs_nothing():
    research = FakeResearch()
    assert await GroundingSource(research).related_signals("Q1969250", region_code="IN-KL") == [] and research.questions == []


async def test_a_topic_is_researched_in_its_region():
    research = FakeResearch()
    (claim,) = await GroundingSource(research).related_signals("festival:thaipusam", region_code="IN-TN")
    assert "thaipusam" in research.questions[0] and claim.subject == "festival:thaipusam"


async def test_provider_failures_become_a_typed_source_error_without_details():
    research = FakeResearch()
    research.error = type("LLMError", (Exception,), {"code": "BUDGET_EXCEEDED"})("secret detail")
    with pytest.raises(SourceHttpError) as err:
        await GroundingSource(research).related_signals("region:IN-TN", region_code="IN-TN")
    assert "BUDGET_EXCEEDED" in str(err.value) and "secret detail" not in str(err.value)


@pytest.mark.parametrize(("url", "title", "group"), [
    ("https://hi.wikipedia.org/wiki/x", None, "wikimedia"),
    ("https://redirect.test/abc", "timesofindia.indiatimes.com", "web:timesofindia.indiatimes.com"),
    ("https://www.nic.in/page", "A page title with spaces", "web:www.nic.in"),
])
def test_independence_group_for_citations(url, title, group):
    assert citation_group(url, title) == group
