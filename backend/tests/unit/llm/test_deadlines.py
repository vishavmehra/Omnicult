"""Defect #4: every provider call is bounded by a per-request timeout and an overall deadline."""

import asyncio
import time
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.llm.gateway import CAPABILITY_LIMITS, Completion, DeadlinedCapability, LLMError, LLMGateway
from app.llm.smoke import SmokeOut
from app.llm.fixture import FixtureLLMProvider
from tests.unit.workflows.scenario import offline_settings


class Slow:
    name = "slow"

    def __init__(self, seconds: float):
        self.seconds = seconds
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        await asyncio.sleep(self.seconds)
        return Completion(text='{"sentiment": "positive", "confusion_level": 0.1, "summary": "ok"}')


async def test_chat_call_has_an_overall_deadline():
    settings = Settings(_env_file=None, google_cloud_project="p")
    gateway = LLMGateway(settings, provider=Slow(1.0), deadline_seconds=0.1)
    started = time.perf_counter()
    with pytest.raises(LLMError) as caught:
        await gateway.generate_structured(task="extraction", stage="s", agent="a", system="s", user="u",
                                          schema=SmokeOut, prompt_version="p")
    assert time.perf_counter() - started < 0.6
    assert caught.value.code == "PROVIDER_TIMEOUT" and caught.value.retryable
    assert caught.value.trace.status == "failed" and caught.value.trace.error_code == "PROVIDER_TIMEOUT"


def test_default_chat_deadline_is_bounded():
    gateway = LLMGateway(offline_settings())
    assert gateway._deadline == offline_settings().llm_request_timeout_seconds * 2.5


class SlowEmbedder:
    space = "space-1"

    def is_configured(self) -> bool:
        return True

    async def embed(self, texts, *, kind="document", stage="embedding", agent="retrieval"):
        await asyncio.sleep(0.3)
        return len(texts)


async def test_capability_deadline_scales_with_batches_and_raises_typed_error():
    wrapper = DeadlinedCapability("embeddings", SlowEmbedder(), request_timeout=30, deadline=0.05, provider="google",
                                  model="emb", batch_size=64)
    assert wrapper.space == "space-1" and wrapper.is_configured()  # plain attributes pass through
    with pytest.raises(LLMError) as caught:
        await wrapper.embed(["text"] * 130, kind="document", stage="indexing", agent="retrieval")  # 3 batches: 0.15 s
    error = caught.value
    assert error.code == "PROVIDER_TIMEOUT" and error.retryable
    assert (error.trace.stage, error.trace.provider, error.trace.model_id) == ("indexing", "google", "emb")
    roomy = DeadlinedCapability("embeddings", SlowEmbedder(), request_timeout=30, deadline=1.0, provider="google",
                                model="emb", batch_size=64)
    assert await roomy.embed(["text"] * 2) == 2


def test_capabilities_get_their_own_request_timeout():
    settings = Settings(_env_file=None, google_cloud_project="p", gemini_embedding_dimensions=768)
    wrapper = LLMGateway(settings).capability("embeddings")
    assert isinstance(wrapper, DeadlinedCapability)
    assert (wrapper.request_timeout, wrapper.deadline) == CAPABILITY_LIMITS["embeddings"] == (30.0, 60.0)
    assert wrapper.client._settings.llm_request_timeout_seconds == 30.0  # the adapter's SDK timeout
    assert LLMGateway(settings, fixture=True).capability("embeddings") is None  # demo never reaches a provider
    assert LLMGateway(offline_settings()).capability("vision") is None  # not configured: reported, never substituted


def test_every_capability_deadline_outlasts_its_request_timeout_so_a_fast_failure_can_be_retried():
    assert set(CAPABILITY_LIMITS) == {"embeddings", "vision", "image_generation", "tts", "grounded_research", "transcribe", "music"}
    for name, (request_timeout, deadline) in CAPABILITY_LIMITS.items():
        assert deadline > request_timeout, name
    assert CAPABILITY_LIMITS["vision"] == (40.0, 75.0) and CAPABILITY_LIMITS["transcribe"] == (60.0, 120.0)
