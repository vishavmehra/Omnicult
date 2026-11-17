"""EmbeddingClient on a fake Gen AI client: request shape, ordering, normalisation, retries, metering, configuration."""

import asyncio
import math

import pytest

from app.llm.budget import BudgetGuard, InMemoryUsageSink, Meter
from app.llm.embeddings import EmbeddingClient
from app.llm.gateway import LLMError
from tests.unit.llm.genai_fakes import FakeClient, api_error, embedding_reply, settings

MODEL = "gemini-embedding-2"


def vectors_for(call) -> object:
    """One 3-dimensional vector per input text, [index+1, 0, 0] scaled so normalisation is visible."""
    return embedding_reply([[float(len(text)), 0.0, 0.0] for text in call.contents])


def client_for(script, **overrides) -> tuple[EmbeddingClient, FakeClient]:
    fake = FakeClient(embed=script)
    return EmbeddingClient(settings(**overrides), client=fake, backoff_seconds=0), fake


async def test_one_request_per_text_in_order_with_normalised_vectors_and_the_space():
    client, fake = client_for([vectors_for] * 3)
    result = await client.embed(["aa", "  bbb   b ", "c"])
    assert [c.contents for c in fake.models.embed_calls] == [["aa"], ["bbb b"], ["c"]]  # gemini-embedding-2: one text each
    assert all(c.model == MODEL and c.config.output_dimensionality == 3 for c in fake.models.embed_calls)
    assert result.vectors == [[1.0, 0.0, 0.0]] * 3  # unit length whatever the raw magnitude
    assert result.space.key == f"google:{MODEL}:3:emb-v2"
    assert result.trace.status == "completed" and result.trace.provider == "google" and result.trace.model_id == MODEL
    assert result.trace.usage.input_tokens == 12 and result.trace.usage.estimated_cost_usd > 0


async def test_results_keep_input_order_even_when_responses_finish_out_of_order():
    async def slow_first(call):
        await asyncio.sleep(0.05 if call.contents == ["first"] else 0)
        return embedding_reply([[1.0, 0.0, 0.0] if call.contents == ["first"] else [0.0, 1.0, 0.0]])

    client, _ = client_for([slow_first, slow_first])
    result = await client.embed(["first", "second"])
    assert result.vectors == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]


async def test_task_types_only_for_models_that_use_them():
    client, fake = client_for([vectors_for], gemini_embedding_model="gemini-embedding-001")
    await client.embed(["q"], kind="query")
    assert fake.models.embed_calls[0].config.task_type == "RETRIEVAL_QUERY"
    client, fake = client_for([vectors_for])
    await client.embed(["q"], kind="query")
    assert fake.models.embed_calls[0].config.task_type is None


async def test_vectors_of_another_dimension_are_rejected():
    client, _ = client_for([embedding_reply([[1.0] * 5])])
    with pytest.raises(LLMError) as caught:
        await client.embed(["hiking"])
    assert caught.value.code == "PROVIDER_ERROR" and not caught.value.retryable


async def test_transient_errors_are_retried_and_permanent_ones_are_not():
    client, fake = client_for([api_error(503), vectors_for])
    result = await client.embed(["hiking"])
    assert len(fake.models.embed_calls) == 2 and result.trace.retries == 1

    client, fake = client_for([api_error(400, "INVALID_ARGUMENT")])
    with pytest.raises(LLMError) as caught:
        await client.embed(["hiking"])
    assert len(fake.models.embed_calls) == 1
    assert (caught.value.code, caught.value.retryable, caught.value.trace.status) == ("PROVIDER_ERROR", False, "failed")

    client, _ = client_for([api_error(504, "DEADLINE_EXCEEDED")] * 3)
    with pytest.raises(LLMError) as caught:
        await client.embed(["hiking"])
    assert caught.value.code == "PROVIDER_TIMEOUT" and caught.value.retryable


async def test_a_failed_request_cancels_the_rest_and_empty_text_is_refused():
    client, _ = client_for([api_error(400)] + [vectors_for] * 5)
    with pytest.raises(LLMError):
        await client.embed([f"t{i}" for i in range(6)])
    client, _ = client_for([])
    with pytest.raises(ValueError):
        await client.embed(["ok", "   "])


async def test_budget_is_checked_before_each_request_and_usage_is_recorded():
    sink = InMemoryUsageSink()
    meter = Meter(sink, BudgetGuard(sink, run_budget_usd=0, daily_budget_usd=0.000001))
    fake = FakeClient(embed=[vectors_for])
    client = EmbeddingClient(settings(), client=fake, meter=meter, backoff_seconds=0)
    with pytest.raises(LLMError) as caught:
        await client.embed(["a long enough sentence to cost something " * 50])
    assert caught.value.code == "BUDGET_EXCEEDED" and fake.models.embed_calls == []

    fake = FakeClient(embed=[vectors_for])
    client = EmbeddingClient(settings(), client=fake, meter=Meter(sink), backoff_seconds=0)
    await client.embed(["hello"])
    (event,) = sink.events
    assert (event.capability, event.model, event.status, event.input_tokens) == ("embeddings", MODEL, "ok", 4)  # the API-reported count


@pytest.mark.parametrize("overrides", [
    {"google_cloud_project": None}, {"gemini_embedding_dimensions": 0},
    {"gemini_embedding_model": "gemini-3.8-flash"},  # a chat model is not an embedder
])
async def test_unconfigured_client_raises_provider_not_configured(overrides: dict) -> None:
    client = EmbeddingClient(settings(**overrides))
    assert not client.is_configured()
    with pytest.raises(LLMError) as caught:
        await client.embed(["hiking"])
    assert caught.value.code == "PROVIDER_NOT_CONFIGURED"


def test_normalisation_is_unit_length():
    from app.llm.embeddings import _normalised

    assert math.isclose(math.sqrt(sum(v * v for v in _normalised([3.0, 4.0]))), 1.0)
    assert _normalised([0.0, 0.0]) == [0.0, 0.0]
