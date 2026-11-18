"""BudgetGuard, Meter, UsageSink and the Google model registry (routing chain, price table, cost estimates)."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.llm import registry
from app.llm.budget import (
    BudgetExceeded, BudgetGuard, InMemoryUsageSink, Meter, UsageContext, UsageEvent, current_run_id, current_usage_context,
    failure_code, get_default_usage_sink, metered, run_scope, set_default_usage_sink, usage_scope,
)
from app.llm.gateway import ProviderError
from app.schemas.common import Usage
from tests.unit.llm.genai_fakes import settings


def event(cost, *, run_id=None, when=None) -> UsageEvent:
    return UsageEvent(timestamp=when or datetime.now(UTC), capability="chat", provider="google", model="m", status="ok",
                      run_id=run_id, estimated_cost_usd=cost)


# --- sink and guard ---------------------------------------------------------------------------------------------


async def test_in_memory_sink_sums_by_run_and_by_utc_day():
    sink = InMemoryUsageSink()
    yesterday = datetime.now(UTC) - timedelta(days=1)
    for e in (event(1.0, run_id="a"), event(2.0, run_id="a"), event(4.0, run_id="b"), event(8.0, when=yesterday)):
        await sink.record(e)
    assert await sink.spent_usd(run_id="a") == 3.0 and await sink.spent_usd(run_id="b") == 4.0
    assert await sink.spent_usd() == 7.0  # today only
    assert await sink.spent_usd(day=yesterday.date()) == 8.0


async def test_guard_refuses_a_call_that_would_cross_the_run_or_day_ceiling():
    sink = InMemoryUsageSink()
    guard = BudgetGuard(sink, run_budget_usd=1.0, daily_budget_usd=2.0)
    await sink.record(event(0.9, run_id="r"))
    with pytest.raises(BudgetExceeded) as caught:
        await guard.reserve(0.2, "r")
    assert (caught.value.scope, caught.value.limit) == ("run", 1.0)
    await guard.reserve(0.2, "other-run")  # a different run is unaffected by r's spend
    await sink.record(event(1.5, run_id="x"))
    with pytest.raises(BudgetExceeded) as caught:
        await guard.reserve(0.6, "fresh-run")  # 0.9 + 1.5 + 0.2 reserved + 0.6 > 2.0
    assert caught.value.scope == "day"


async def test_reserved_estimates_count_so_parallel_calls_cannot_jointly_overshoot():
    guard = BudgetGuard(InMemoryUsageSink(), run_budget_usd=1.0, daily_budget_usd=0)
    await guard.reserve(0.6, "r")
    with pytest.raises(BudgetExceeded):
        await guard.reserve(0.6, "r")  # the first call is still in flight
    guard.release(0.6, "r")
    await guard.reserve(0.6, "r")  # released, so it fits again


async def test_non_positive_ceilings_disable_their_check():
    guard = BudgetGuard(InMemoryUsageSink(), run_budget_usd=0, daily_budget_usd=0)
    await guard.reserve(1e6, "r")


async def test_meter_records_cost_failure_and_releases_the_reservation():
    sink = InMemoryUsageSink()
    guard = BudgetGuard(sink, run_budget_usd=10.0, daily_budget_usd=0)
    meter = Meter(sink, guard)
    with run_scope("r1"):
        async with meter.call(capability="chat", model="gemini-3.5-flash-lite", estimate_usd=0.5, stage="s", agent="a") as rec:
            rec.usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
        with pytest.raises(RuntimeError):
            async with meter.call(capability="chat", model="gemini-3.5-flash-lite", estimate_usd=0.5) as rec:
                raise RuntimeError("boom")
    ok, failed = sink.events
    assert ok.estimated_cost_usd == pytest.approx(0.30 + 2.50) and ok.run_id == "r1" and ok.status == "ok"
    assert (failed.status, failed.estimated_cost_usd) == ("error", None)
    assert guard._reserved_total == 0  # both reservations were released


async def test_meter_refuses_before_running_the_body():
    sink = InMemoryUsageSink()
    meter = Meter(sink, BudgetGuard(sink, run_budget_usd=0, daily_budget_usd=0.01))
    ran = []
    with pytest.raises(BudgetExceeded):
        async with meter.call(capability="image_generation", model="gemini-3.1-flash-image", estimate_usd=0.07):
            ran.append(True)
    assert ran == [] and list(sink.events) == []


async def test_unknown_models_are_budgeted_at_the_standin_price_and_flagged():
    sink = InMemoryUsageSink()
    async with Meter(sink).call(capability="chat", model="not-in-the-registry") as rec:
        rec.usage = Usage(input_tokens=1_000_000, output_tokens=0)
    (e,) = sink.events
    assert e.price_known is False and e.estimated_cost_usd == pytest.approx(registry.UNKNOWN_MODEL_PRICE.input_per_m)


async def test_a_failing_sink_never_fails_the_call():
    class Broken:
        async def record(self, event):
            raise OSError("db down")

        async def spent_usd(self, **kw):
            return 0.0

    async with Meter(Broken()).call(capability="chat", model="gemini-3.5-flash-lite"):
        pass


async def test_metered_without_a_meter_is_a_noop_and_run_scope_nests():
    async with metered(None, capability="chat", model="m") as rec:
        rec.usage = Usage()
    assert current_run_id() is None
    with run_scope("outer"):
        with run_scope("inner"):
            assert current_run_id() == "inner"
        assert current_run_id() == "outer"
    assert current_run_id() is None


async def test_run_scope_follows_the_task_not_the_process():
    seen = {}

    async def worker(name):
        with run_scope(name):
            await asyncio.sleep(0)
            seen[name] = current_run_id()

    await asyncio.gather(worker("x"), worker("y"))
    assert seen == {"x": "x", "y": "y"}


def test_default_sink_is_replaceable():
    original = get_default_usage_sink()
    replacement = InMemoryUsageSink()
    set_default_usage_sink(replacement)
    assert get_default_usage_sink() is replacement
    set_default_usage_sink(original)


# --- registry ---------------------------------------------------------------------------------------------------


def chain(task, **overrides):
    return registry.tier_chain(settings(**overrides), task)


def test_tier_chain_orders_models_and_respects_the_task_floor():
    assert chain("risk_analysis") == [("reasoning", "gemini-4-argon"), ("default", "gemini-3.8-flash")]
    assert chain("research_synthesis") == [("default", "gemini-3.8-flash"), ("fast", "gemini-3.5-flash-lite")]
    assert chain("extraction") == [("fast", "gemini-3.5-flash-lite")]  # nothing below fast
    assert chain("creative_adaptation") == [("default", "gemini-3.8-flash")]  # floor default: no flash-lite fallback
    same = chain("risk_analysis", gemini_model_reasoning="gemini-3.8-flash")
    assert same == [("reasoning", "gemini-3.8-flash")]  # identical models are not tried twice


def test_every_task_has_a_tier_and_a_floor_not_above_it():
    rank = {"fast": 0, "default": 1, "reasoning": 2}
    assert set(registry.TASK_TIERS) == set(registry.TASK_FLOOR)
    assert all(rank[registry.TASK_FLOOR[t]] <= rank[registry.TASK_TIERS[t]] for t in registry.TASK_TIERS)


def test_capability_models_come_from_settings():
    s = settings(gemini_model_image="img", gemini_model_tts="tts", gemini_embedding_model="emb", gemini_model_live="live")
    assert [registry.capability_model(s, c) for c in ("image_generation", "tts", "embeddings", "live", "vision")] == [
        "img", "tts", "emb", "live", "gemini-3.8-flash"]


def test_default_settings_name_only_registered_models_with_the_right_capability():
    s = Settings(_env_file=None)
    for capability in ("chat", "vision", "image_generation", "tts", "embeddings", "live", "grounded_research"):
        model = registry.capability_model(s, capability)
        assert registry.supports(model, capability), (capability, model)
    for tier in ("fast", "default", "reasoning"):
        assert registry.supports(registry.tier_model(s, tier), "chat")


def test_cost_is_tokens_times_price_with_thinking_in_output():
    cost = registry.estimate_cost("gemini-3.5-flash-lite", input_tokens=2_000_000, output_tokens=1_000_000)
    assert cost.known and cost.usd == pytest.approx(2 * 0.30 + 2.50)
    unknown = registry.estimate_cost("something-new", input_tokens=1_000_000)
    assert not unknown.known and unknown.usd == registry.UNKNOWN_MODEL_PRICE.input_per_m


def test_published_price_changes_apply_from_their_date():
    before = registry.estimate_cost("gemini-3.8-flash", input_tokens=1_000_000, output_tokens=1_000_000, on=date(2026, 12, 31))
    after = registry.estimate_cost("gemini-3.8-flash", input_tokens=1_000_000, output_tokens=1_000_000, on=date(2027, 1, 1))
    assert before.usd == pytest.approx(0.75 + 3.75) and after.usd == pytest.approx(1.50 + 7.50)
    argon = [registry.estimate_cost("gemini-4-argon", output_tokens=1_000_000, on=d).usd for d in (date(2026, 11, 30), date(2026, 12, 1))]
    assert argon == [pytest.approx(10.0), pytest.approx(20.0)]


def test_long_prompts_bill_at_the_long_context_rate():
    short = registry.estimate_cost("gemini-3.1-pro-preview", input_tokens=100_000).usd
    long = registry.estimate_cost("gemini-3.1-pro-preview", input_tokens=300_000).usd
    assert short == pytest.approx(0.2) and long == pytest.approx(1.2)


def test_media_costs_use_flat_image_and_per_second_audio_prices():
    image = registry.estimate_cost("gemini-3.1-flash-image", input_tokens=1_000_000, output_tokens=5000, images=2)
    assert image.usd == pytest.approx(0.50 + 2 * 0.067)  # image output tokens are inside the flat figure
    speech = registry.estimate_cost("gemini-3.8-flash-tts", audio_seconds=10.0, on=date(2026, 11, 17))
    assert speech.usd == pytest.approx(10 * 9.0 * 25 / 1e6)
    assert registry.estimate_cost("gemini-3.5-flash-lite", grounded_requests=1000).usd == pytest.approx(14.0)
    assert registry.estimate_cost("lyria-002", audio_seconds=30).usd == pytest.approx(0.06)


def test_thinking_level_is_applied_only_to_models_that_accept_it():
    assert registry.thinking_level_for("gemini-3.8-flash", "default") == "LOW"
    assert registry.thinking_level_for("gemini-4-argon", "reasoning") == "MEDIUM"
    assert registry.thinking_level_for("gemini-3.5-flash-lite", "fast") is None
    assert registry.thinking_level_for("unknown", "fast") is None and registry.thinking_level_for("gemini-3.8-flash", None) is None


async def test_usage_scope_attributes_events_counts_against_the_run_and_restores():
    sink = InMemoryUsageSink()
    meter = Meter(sink)
    ids = [uuid4() for _ in range(5)]
    where = UsageContext(workspace_id=ids[0], project_id=ids[1], campaign_id=ids[2], user_id=ids[3], run_id=ids[4])
    async with meter.call(capability="chat", model="m"):
        pass
    with usage_scope(where):
        assert current_usage_context() == where and current_run_id() == str(ids[4])
        async with meter.call(capability="chat", model="m"):
            pass
        with usage_scope(UsageContext(user_id=ids[3])):  # an inner scope replaces the context and the run
            async with meter.call(capability="chat", model="m"):
                pass
            assert current_run_id() == str(ids[4])  # no run in the inner context: the outer run id stays
    assert current_usage_context() == UsageContext() and current_run_id() is None
    outside, inside, inner = sink.events
    assert (outside.workspace_id, outside.run_id) == (None, None)
    assert (inside.workspace_id, inside.project_id, inside.campaign_id, inside.user_id, inside.run_id) == (*ids[:4], str(ids[4]))
    assert (inner.workspace_id, inner.user_id) == (None, ids[3])
    assert await sink.spent_usd(run_id=str(ids[4])) == 0.0


async def test_a_failed_attempt_is_recorded_with_the_code_the_error_maps_to():
    sink = InMemoryUsageSink()
    meter = Meter(sink)
    for error in (ProviderError("t", transient=True, timeout=True), ProviderError("b", transient=False, blocked=True),
                  ProviderError("x", transient=True), RuntimeError("boom"), asyncio.CancelledError()):
        with pytest.raises(BaseException):
            async with meter.call(capability="vision", model="m"):
                raise error
    assert [(e.status, e.error_code, e.estimated_cost_usd) for e in sink.events] == [
        ("error", "PROVIDER_TIMEOUT", None), ("error", "CONTENT_BLOCKED", None), ("error", "PROVIDER_ERROR", None),
        ("error", "PROVIDER_ERROR", None), ("error", "CANCELLED", None)]
    assert failure_code(TimeoutError()) == "PROVIDER_TIMEOUT"


def test_transcribe_is_routed_to_the_default_model_and_only_audio_capable_models_support_it():
    s = settings()
    assert registry.capability_model(s, "transcribe") == s.gemini_model_default == "gemini-3.8-flash"
    assert all(registry.supports(m, "transcribe") for m in (
        "gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-4-argon", "gemini-3.1-pro-preview"))
    assert not any(registry.supports(m, "transcribe") for m in ("gemini-embedding-2", "gemini-3.1-flash-image", "gemini-3.8-flash-tts", "unknown"))
