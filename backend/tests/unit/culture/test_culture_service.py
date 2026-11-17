"""CultureService: fan-out, call log, caching (successes only), partial results, shared ambiguity rule."""

from datetime import UTC, datetime, timedelta

from app.integrations.culture.base import (
    CultureSourceError,
    EntityCandidate,
    EntityResolution,
    SourceBase,
    SourceDescriptor,
    SourceNetworkError,
    decide_resolution,
    now_utc,
)
from app.integrations.culture.service import CultureService, InMemoryCacheStore
from app.schemas.claims import ClaimDraft, ClaimScope, SourceRef

ALL = frozenset({"resolve_entity", "related_signals", "audience_facts", "trend_series", "moments"})


def make_claim(subject: str = "region:IN-TN", value: object = 1) -> ClaimDraft:
    stamp = datetime(2026, 11, 17, tzinfo=UTC)
    source = SourceRef(source_type="curated_reference", source_identifier="u", retrieved_at=stamp, independence_group="g")
    return ClaimDraft(subject=subject, attribute="a", category="custom", value=value, value_text="t",
                      scope=ClaimScope(region_code="IN-TN"), kind="observed", sources=[source], retrieved_at=stamp)


class FakeSource(SourceBase):
    def __init__(self, name: str = "fake", ops: frozenset = ALL, claims: list[ClaimDraft] | None = None, configured: bool = True) -> None:
        self.name, self.configured, self.calls, self.error = name, configured, 0, None
        self.claims = claims if claims is not None else [make_claim()]
        self.descriptor = SourceDescriptor(name=name, source_type="curated_reference", supported_operations=ops, scope="t",
                                           coverage_limitations=[])

    def is_configured(self) -> bool:
        return self.configured

    async def audience_facts(self, region_code: str) -> list[ClaimDraft]:
        self.calls += 1
        if self.error:
            raise self.error
        return self.claims

    async def resolve_entity(self, query, *, language=None, region_code=None) -> EntityResolution:
        self.calls += 1
        candidates = [EntityCandidate(entity_id=f"{self.name}-1", label=query, source=self.name, match_type="label")]
        return decide_resolution(query, candidates, language=language, region_code=region_code, sources=[self.name], retrieved_at=now_utc())


async def test_success_is_cached_and_logged_as_cached_the_second_time():
    source = FakeSource()
    service = CultureService([source], cache=InMemoryCacheStore())
    first = await service.audience_facts("IN-TN")
    second = await service.audience_facts("IN-TN")
    assert first == second and source.calls == 1
    assert [(r.status, r.cached) for r in service.call_log] == [("ok", False), ("ok", True)]
    assert service.call_log[0].request_hash == service.call_log[1].request_hash
    assert service.call_log[0].source == "fake" and service.call_log[0].operation == "audience_facts"


async def test_errors_are_never_cached_and_do_not_raise():
    source = FakeSource()
    source.error = SourceNetworkError("fake", "audience_facts", "network error (ConnectError)")
    service = CultureService([source], cache=InMemoryCacheStore())
    assert await service.audience_facts("IN-TN") == []
    assert service.call_log[0].status == "error" and service.call_log[0].error_type == "network"
    assert "ConnectError" in (service.call_log[0].error or "")
    assert service.cache.entries == {}  # nothing stored for the failure
    source.error = None
    assert len(await service.audience_facts("IN-TN")) == 1 and source.calls == 2  # the retry reached the source
    await service.audience_facts("IN-TN")
    assert source.calls == 2  # and its success is now cached


async def test_unexpected_exceptions_are_contained_and_not_cached():
    source = FakeSource()
    source.error = RuntimeError("bug")
    service = CultureService([source], cache=InMemoryCacheStore())
    assert await service.audience_facts("IN-TN") == []
    assert service.call_log[0].status == "error" and service.call_log[0].error_type == "RuntimeError"
    assert service.cache.entries == {}


async def test_an_empty_successful_result_is_cached_as_empty():
    source = FakeSource(claims=[])
    service = CultureService([source], cache=InMemoryCacheStore())
    await service.audience_facts("IN-TN")
    await service.audience_facts("IN-TN")
    assert source.calls == 1 and [r.status for r in service.call_log] == ["empty", "empty"]


async def test_expired_entries_are_not_served():
    now = [datetime(2026, 11, 17, tzinfo=UTC)]
    source = FakeSource()
    service = CultureService([source], cache=InMemoryCacheStore(clock=lambda: now[0]))
    await service.audience_facts("IN-TN")
    now[0] += timedelta(days=31)  # audience_facts TTL is 30 days
    await service.audience_facts("IN-TN")
    assert source.calls == 2


async def test_one_failing_source_leaves_the_others_answers():
    good, bad = FakeSource("good"), FakeSource("bad")
    bad.error = CultureSourceError("bad", "audience_facts", "boom")
    service = CultureService([bad, good])
    claims = await service.audience_facts("IN-TN")
    assert len(claims) == 1
    assert {(r.source, r.status) for r in service.call_log} == {("good", "ok"), ("bad", "error")}


async def test_unconfigured_and_unsupported_sources_are_skipped_not_called():
    off = FakeSource("off", configured=False)
    only_moments = FakeSource("moments_only", ops=frozenset({"moments"}))
    service = CultureService([off, only_moments])
    assert await service.audience_facts("IN-TN") == []
    assert off.calls == 0 and only_moments.calls == 0 and service.call_log == []
    assert service.skipped_sources() == ["off"] and service.is_configured()  # one source is still usable


async def test_the_per_call_log_sink_receives_only_that_calls_records():
    service = CultureService([FakeSource()])
    sink: list = []
    await service.audience_facts("IN-TN", log=sink)
    await service.audience_facts("IN-MH")
    assert len(sink) == 1 and len(service.call_log) == 2


async def test_two_sources_with_the_same_exact_match_are_ambiguous():
    service = CultureService([FakeSource("a"), FakeSource("b")])
    result = await service.resolve_entity("Pongal", language="en", region_code="IN-TN")
    assert result.status == "ambiguous" and len(result.candidates) == 2 and result.sources == ["a", "b"]


def test_resolution_rule():
    stamp = now_utc()
    kw = dict(language="en", region_code=None, sources=["s"], retrieved_at=stamp)

    def cand(i, label, match="label", text=None):
        return EntityCandidate(entity_id=i, label=label, source="s", match_type=match, matched_text=text or label)

    assert decide_resolution("x", [], **kw).status == "unresolved"
    only = decide_resolution("Onam", [cand("Q1", "Onam"), cand("Q2", "Onam festival", "other", "Onam fest")], **kw)
    assert only.status == "resolved" and only.entity.entity_id == "Q1"
    clash = decide_resolution("Pongal", [cand("Q1", "Makar Sankranti", "alias", "Pongal"), cand("Q2", "Pongal")], **kw)
    assert clash.status == "ambiguous" and [c.entity_id for c in clash.candidates] == ["Q1", "Q2"] and clash.entity is None
    near = decide_resolution("Diwal", [cand("Q1", "Diwali", "other", "Diwali")], **kw)
    assert near.status == "ambiguous" and near.entity is None  # a near match is never promoted
