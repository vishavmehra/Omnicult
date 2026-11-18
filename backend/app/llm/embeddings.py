"""Embedding adapter on Gemini embeddings (Vertex AI or the Gemini Developer API). One configured model = one vector space.

Vectors are L2-normalised here (Gemini returns un-normalised vectors for reduced dimensions) and requested at
GEMINI_EMBEDDING_DIMENSIONS. There is no automatic fallback for embeddings: vectors from another model live in a different
space and are never compared. Switching GEMINI_EMBEDDING_* re-embeds stored text instead (the space key changes).
Queries and documents use Gemini task types where the model supports them (registry `embedding_task_type`).
"""

import asyncio
import math
import time
from dataclasses import dataclass
from typing import Any, Literal

from app.core.config import Settings
from app.llm import google
from app.llm.budget import BudgetExceeded, Meter, metered
from app.llm.gateway import LLMError, ProviderError, budget_llm_error, failure_trace, provider_llm_error
from app.llm.registry import estimate_cost, spec_for
from app.schemas.common import StepTrace, Usage

# Bump when input preparation, task types or normalisation change: it is part of the space key.
EMBEDDING_CONFIG_VERSION = "emb-v2"
MAX_INPUT_CHARS = 24_000  # about 6k tokens, far below the model limits
APPROX_CHARS_PER_TOKEN = 3  # token estimate when the API reports no count
EMBED_CONCURRENCY = 6  # requests in flight at once (one text per request for gemini-embedding-2)


@dataclass(frozen=True)
class EmbeddingSpace:
    """Vectors are comparable only within one space."""

    provider: str
    model: str
    dimensions: int
    config_version: str = EMBEDDING_CONFIG_VERSION

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}:{self.dimensions}:{self.config_version}"


@dataclass(frozen=True)
class Embeddings:
    vectors: list[list[float]]
    space: EmbeddingSpace
    trace: StepTrace


def _normalised(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values] if norm else list(values)


class EmbeddingClient:
    def __init__(self, settings: Settings, *, client: Any = None, meter: Meter | None = None,
                 backoff_seconds: float = 0.5) -> None:
        self._settings, self._backoff, self._client, self._meter = settings, backoff_seconds, client, meter
        model, dimensions = settings.gemini_embedding_model.strip(), settings.gemini_embedding_dimensions
        spec = spec_for(model)
        usable = bool(model and dimensions > 0 and (client is not None or google.is_configured(settings)))
        usable = usable and (spec is None or "embeddings" in spec.capabilities)  # a known chat model is not an embedder
        self.model = model if usable else None
        self.space = EmbeddingSpace("google", model, dimensions) if usable else None
        self.max_batch = spec.embedding_max_batch if spec else 1
        self._task_types = bool(spec and spec.embedding_task_type)

    def is_configured(self) -> bool:
        return self.space is not None

    @property
    def api(self) -> Any:
        if self._client is None:
            self._client = google.build_client(self._settings, timeout_seconds=self._settings.llm_request_timeout_seconds)
        return self._client

    def prepare(self, text: str) -> str:
        return " ".join(text.split())[:MAX_INPUT_CHARS]

    async def embed(
        self, texts: list[str], *, kind: Literal["query", "document"] = "document", stage: str = "embedding",
        agent: str = "retrieval",
    ) -> Embeddings:
        """Embed texts in the configured space. Raises LLMError (never returns vectors of another space)."""
        started = time.perf_counter()
        if self.space is None:
            trace = StepTrace(stage=stage, agent=agent, status="failed", error_code="PROVIDER_NOT_CONFIGURED")
            raise LLMError("PROVIDER_NOT_CONFIGURED", "No embedding model is configured.", retryable=False, trace=trace)
        from google.genai import types

        space = self.space
        inputs = [self.prepare(text) for text in texts]
        if not all(inputs):
            raise ValueError("Cannot embed empty text.")
        config = types.EmbedContentConfig(
            output_dimensionality=space.dimensions,
            task_type=("RETRIEVAL_QUERY" if kind == "query" else "RETRIEVAL_DOCUMENT") if self._task_types else None,
        )
        gate = asyncio.Semaphore(EMBED_CONCURRENCY)

        async def one(batch: list[str]) -> tuple[list[list[float]], int, int]:
            """(vectors, input tokens, retries) for one request; raises LLMError."""
            estimate_tokens = sum(len(t) for t in batch) // APPROX_CHARS_PER_TOKEN + 1

            async def request() -> tuple[Any, int]:
                async with metered(
                    self._meter, capability="embeddings", model=space.model, stage=stage, agent=agent,
                    estimate_usd=estimate_cost(space.model, input_tokens=estimate_tokens).usd,
                ) as record:
                    if self._client is None:  # off the event loop; a credentials failure is mapped like any provider error
                        await google.warm_credentials(self._settings)
                    response = await self.api.aio.models.embed_content(model=space.model, contents=batch, config=config)
                    counted = [getattr(getattr(e, "statistics", None), "token_count", None) for e in response.embeddings or []]
                    record.usage = Usage(
                        input_tokens=int(sum(counted)) if counted and all(c is not None for c in counted) else estimate_tokens
                    )
                    return response, record.usage.input_tokens

            async with gate:
                try:
                    (response, counted_tokens), used = await google.with_retries(
                        request, retries=max(0, self._settings.llm_max_retries), backoff=self._backoff
                    )
                except BudgetExceeded as exc:
                    raise budget_llm_error(
                        exc, failure_trace(stage, agent, "google", space.model, started, "BUDGET_EXCEEDED")) from exc
                except ProviderError as exc:
                    code = "CONTENT_BLOCKED" if exc.blocked else "PROVIDER_ERROR"
                    raise provider_llm_error(exc, failure_trace(stage, agent, "google", space.model, started, code),
                                             timeout_seconds=self._settings.llm_request_timeout_seconds) from exc
            embeddings = response.embeddings or []
            # One text per request for models that fold several inputs into one vector (gemini-embedding-2), so a
            # count mismatch means the response cannot be matched to the inputs.
            if len(embeddings) != len(batch) or any(len(e.values or []) != space.dimensions for e in embeddings):
                trace = failure_trace(stage, agent, "google", space.model, started, "PROVIDER_ERROR")
                raise LLMError("PROVIDER_ERROR", "The embedding provider returned vectors of an unexpected shape.",
                               retryable=False, trace=trace)
            return [_normalised(list(e.values)) for e in embeddings], counted_tokens, used

        tasks = [asyncio.ensure_future(one(inputs[start : start + self.max_batch]))
                 for start in range(0, len(inputs), self.max_batch)]
        try:
            results = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            raise
        vectors = [vector for batch_vectors, _, _ in results for vector in batch_vectors]
        tokens, retries = sum(t for _, t, _ in results), sum(r for _, _, r in results)
        trace = StepTrace(
            stage=stage, agent=agent, status="completed", provider="google", model_id=space.model,
            schema_version=space.key, latency_ms=int((time.perf_counter() - started) * 1000), retries=retries,
            usage=Usage(input_tokens=tokens, total_tokens=tokens,
                        estimated_cost_usd=estimate_cost(space.model, input_tokens=tokens).usd if spec_for(space.model) else None),
        )
        return Embeddings(vectors=vectors, space=space, trace=trace)
