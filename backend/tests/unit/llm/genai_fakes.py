"""Fakes for the Google Gen AI client: scripted responses built from the SDK's real types, no network.

`FakeClient(generate=[...], embed=[...])` stands in for `genai.Client`: each call pops the next scripted item (an exception
to raise, a callable taking the recorded call, or a ready response) and records `model`, `contents` and `config`.
"""

import inspect
from types import SimpleNamespace
from typing import Any

from google.genai import errors, types

from app.core.config import Settings


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "google_genai_backend": "vertex", "google_cloud_project": "test-project", "llm_max_retries": 2,
        "llm_request_timeout_seconds": 5, "gemini_model_fast": "gemini-3.5-flash-lite",
        "gemini_model_default": "gemini-3.8-flash", "gemini_model_reasoning": "gemini-4-argon",
        "gemini_embedding_dimensions": 3,
    }
    return Settings(_env_file=None, **(values | overrides))


def reply(
    text: str, *, finish: str = "STOP", prompt: int | None = 10, out: int | None = 5, thoughts: int | None = None,
    grounding: types.GroundingMetadata | None = None,
) -> types.GenerateContentResponse:
    usage = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=prompt, candidates_token_count=out, thoughts_token_count=thoughts,
        total_token_count=None if prompt is None or out is None else prompt + out + (thoughts or 0),
    )
    candidate = types.Candidate(
        content=types.Content(role="model", parts=[types.Part(text=text)]), finish_reason=finish,
        grounding_metadata=grounding,
    )
    return types.GenerateContentResponse(candidates=[candidate], usage_metadata=usage)


def blob_reply(data: bytes, mime_type: str, *, text: str | None = None, out: int = 100) -> types.GenerateContentResponse:
    parts = ([types.Part(text=text)] if text else []) + [types.Part(inline_data=types.Blob(data=data, mime_type=mime_type))]
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts), finish_reason="STOP")],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=8, candidates_token_count=out,
                                                                  total_token_count=8 + out),
    )


def blocked_prompt(reason: str = "SAFETY") -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason=reason),
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=10, total_token_count=10),
    )


def api_error(code: int, status: str = "ERROR", *, retry_after: str | None = None) -> errors.APIError:
    body = {"error": {"code": code, "status": status, "message": "detail that must never reach a user"}}
    response = SimpleNamespace(headers={"retry-after": retry_after} if retry_after else {})
    cls = errors.ClientError if code < 500 else errors.ServerError
    return cls(code, body, response)  # type: ignore[arg-type]


def embedding_reply(vectors: list[list[float]], tokens: int | None = 4) -> types.EmbedContentResponse:
    return types.EmbedContentResponse(embeddings=[
        types.ContentEmbedding(values=v, statistics=types.ContentEmbeddingStatistics(token_count=tokens)) for v in vectors
    ])


class _Models:
    def __init__(self, generate: list[Any], embed: list[Any]) -> None:
        self.generate, self.embed = list(generate), list(embed)
        self.calls: list[SimpleNamespace] = []
        self.embed_calls: list[SimpleNamespace] = []

    @staticmethod
    async def _next(script: list[Any], call: SimpleNamespace) -> Any:
        item = script.pop(0)
        if isinstance(item, BaseException):
            raise item
        result = item(call) if callable(item) else item
        return await result if inspect.isawaitable(result) else result

    async def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.calls.append(SimpleNamespace(model=model, contents=contents, config=config))
        return await self._next(self.generate, self.calls[-1])

    async def embed_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.embed_calls.append(SimpleNamespace(model=model, contents=contents, config=config))
        return await self._next(self.embed, self.embed_calls[-1])


class FakeClient:
    def __init__(self, generate: list[Any] | None = None, embed: list[Any] | None = None) -> None:
        self.models = _Models(generate or [], embed or [])
        self.aio = SimpleNamespace(models=self.models)

    @property
    def calls(self) -> list[SimpleNamespace]:
        return self.models.calls
