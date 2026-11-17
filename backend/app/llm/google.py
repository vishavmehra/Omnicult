"""Google Gen AI provider: the only AI runtime behind the gateway (Vertex AI or the Gemini Developer API).

`GoogleGenAIProvider` implements the gateway's `ChatProvider` protocol. `build_client` is the one place a `genai.Client`
is created; tests inject a fake client (or patch this function), so nothing here needs the network to be tested.
Pydantic validation in the gateway stays authoritative: the JSON Schema sent to Gemini is only a hint, stripped of
keywords the API rejects. Errors are mapped to `ProviderError` (transient / timeout / blocked / permanent) and never carry
request or credential text.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import Settings
from app.llm.budget import BudgetExceeded
from app.llm.gateway import ChatRequest, Completion, ProviderError
from app.schemas.common import Usage

# JSON Schema keywords Gemini's `response_json_schema` accepts (Gen AI SDK 3.4 reference). Everything else is dropped.
_SCHEMA_KEYS = frozenset({
    "$id", "$defs", "$ref", "$anchor", "type", "format", "title", "description", "enum", "items", "prefixItems",
    "minItems", "maxItems", "minimum", "maximum", "anyOf", "oneOf", "properties", "additionalProperties", "required",
})
_FORMATS = frozenset({"date-time", "date", "time"})
_SCHEMA_NODE_MAPS = ("properties", "$defs")  # {name: schema}
_SCHEMA_NODES = ("items", "additionalProperties", "prefixItems", "anyOf", "oneOf")  # schema or list of schemas

# finish reasons that mean the model declined or was filtered, as opposed to failing
BLOCKING_FINISH_REASONS = frozenset({
    "SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY", "IMAGE_PROHIBITED_CONTENT",
    "IMAGE_RECITATION",
})
RETRY_AFTER_CAP_SECONDS = 10.0
_TIMEOUT_NAMES = frozenset({"TimeoutException", "ReadTimeout", "ConnectTimeout", "WriteTimeout", "PoolTimeout", "TimeoutError"})
_CONNECTION_NAMES = frozenset({
    "ConnectError", "NetworkError", "TransportError", "ConnectionError", "RemoteProtocolError", "ReadError", "WriteError",
    "ClientConnectionError", "ServerDisconnectedError",
})


# --- client ---------------------------------------------------------------------------------------------------


def is_configured(settings: Settings) -> bool:
    """Credentials for the selected backend are present. Application Default Credentials cannot be checked without a
    request, so for Vertex AI this means a project id is set."""
    if settings.google_genai_backend == "vertex":
        return bool(settings.google_cloud_project)
    return bool(settings.gemini_api_key and settings.gemini_api_key.get_secret_value().strip())


def build_client(settings: Settings, *, location: str | None = None, timeout_seconds: float | None = None) -> Any:
    """The one `genai.Client` factory. `location` overrides GOOGLE_CLOUD_LOCATION (image models need `global`)."""
    from google import genai
    from google.genai import types

    options = types.HttpOptions(timeout=int(timeout_seconds * 1000)) if timeout_seconds else None
    if settings.google_genai_backend == "vertex":
        return genai.Client(
            vertexai=True, project=settings.google_cloud_project, location=location or settings.google_cloud_location,
            http_options=options,
        )
    assert settings.gemini_api_key is not None
    return genai.Client(api_key=settings.gemini_api_key.get_secret_value(), http_options=options)


# --- request mapping ------------------------------------------------------------------------------------------


def to_gemini_schema(node: Any) -> Any:
    """Strip JSON Schema keywords Gemini rejects (lengths, patterns, defaults, ...) and turn `const` into a one-value
    enum. Property names are never touched. The result is a hint; the gateway validates the reply against Pydantic."""
    if isinstance(node, list):
        return [to_gemini_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:  # a $ref sub-schema may carry only $-keywords
        return {key: value for key, value in node.items() if key.startswith("$") and key in _SCHEMA_KEYS}
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "const" and "enum" not in node:
            out["enum"] = [value]
        elif key not in _SCHEMA_KEYS:
            continue
        elif key == "format":
            if value in _FORMATS:
                out[key] = value
        elif key in _SCHEMA_NODE_MAPS:
            out[key] = {name: to_gemini_schema(sub) for name, sub in value.items()}
        elif key in _SCHEMA_NODES:
            out[key] = to_gemini_schema(value)
        else:
            out[key] = value
    return out


def _part(spec: Any, types: Any) -> Any:
    if isinstance(spec, str):
        return types.Part(text=spec or "(no output)")  # Gemini rejects empty text parts
    kind = spec.get("type")
    if kind == "text":
        return types.Part(text=spec.get("text") or "(no output)")
    if kind in ("image", "audio", "inline_data"):
        return types.Part.from_bytes(data=spec["data"], mime_type=spec.get("mime_type") or spec["media_type"])
    raise ValueError(f"Unsupported message part type {kind!r}.")


def to_contents(messages: list[dict[str, Any]]) -> tuple[str | None, list[Any]]:
    """OpenAI-style role/content messages -> (system_instruction, Gemini contents). `assistant` becomes role `model`;
    a content value is a string or a list of parts: {"type": "text", "text"} or {"type": "image", "mime_type", "data"}."""
    from google.genai import types

    system: list[str] = []
    contents: list[Any] = []
    for message in messages:
        role, content = message["role"], message["content"]
        if role == "system":
            system.append(content if isinstance(content, str) else "\n".join(p.get("text", "") for p in content))
            continue
        parts = [_part(content, types)] if isinstance(content, str) else [_part(p, types) for p in content]
        contents.append(types.Content(role="model" if role == "assistant" else "user", parts=parts))
    return ("\n\n".join(system) or None), contents


def thinking_config(level: str | None) -> Any:
    if not level:
        return None
    from google.genai import types

    return types.ThinkingConfig(thinking_level=level)


# --- response mapping -----------------------------------------------------------------------------------------


def usage_from(meta: Any) -> Usage | None:
    """Gen AI usage_metadata -> Usage. Output tokens include thinking tokens (they bill as output)."""
    if meta is None:
        return None
    prompt, candidates, thoughts = meta.prompt_token_count, meta.candidates_token_count, meta.thoughts_token_count
    tool_prompt = getattr(meta, "tool_use_prompt_token_count", None) or 0
    input_tokens = None if prompt is None else prompt + tool_prompt
    output_tokens = None if candidates is None and thoughts is None else (candidates or 0) + (thoughts or 0)
    total = meta.total_token_count
    if total is None and input_tokens is not None and output_tokens is not None:
        total = input_tokens + output_tokens
    if input_tokens is None and output_tokens is None and total is None:
        return None
    return Usage(input_tokens=input_tokens, output_tokens=output_tokens, thinking_tokens=thoughts, total_tokens=total)


def _name(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def check_blocked(response: Any) -> None:
    """Raise ProviderError(blocked=True) when the prompt or the first candidate was stopped by a safety filter."""
    feedback = getattr(response, "prompt_feedback", None)
    if feedback is not None and feedback.block_reason:
        raise ProviderError(f"blocked: {_name(feedback.block_reason)}", transient=False, blocked=True)
    candidates = response.candidates or []
    if candidates and _name(candidates[0].finish_reason) in BLOCKING_FINISH_REASONS:
        raise ProviderError(f"blocked: {_name(candidates[0].finish_reason)}", transient=False, blocked=True)


def visible_text(response: Any) -> str:
    """The answer text: parts of the first candidate that are text and not model thoughts."""
    candidates = response.candidates or []
    content = candidates[0].content if candidates else None
    parts = (content.parts if content else None) or []
    return "".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False))


# --- error mapping --------------------------------------------------------------------------------------------


def _retry_after(exc: Any) -> float | None:
    value: Any = None
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is not None:
        value = headers.get("retry-after")
    if value is None:  # google.rpc.RetryInfo inside the error body: {"@type": ".../RetryInfo", "retryDelay": "34s"}
        details = getattr(exc, "details", None)
        error = details.get("error", details) if isinstance(details, dict) else {}
        for item in (error.get("details") or []) if isinstance(error, dict) else []:
            if isinstance(item, dict) and str(item.get("@type", "")).endswith("RetryInfo"):
                value = str(item.get("retryDelay", "")).rstrip("s") or None
    try:
        return min(float(value), RETRY_AFTER_CAP_SECONDS) if value else None
    except (TypeError, ValueError):
        return None


def map_exception(exc: BaseException) -> ProviderError:
    """Gen AI SDK / transport exception -> ProviderError. The message is a status line, never the request or body."""
    if isinstance(exc, ProviderError):
        return exc
    names = {cls.__name__ for cls in type(exc).__mro__}
    code = getattr(exc, "code", None)
    if "APIError" in names and isinstance(code, int):
        if code in (408, 504):
            return ProviderError(f"HTTP {code}", transient=True, timeout=True)
        if code == 429:
            return ProviderError("HTTP 429", transient=True, retry_after=_retry_after(exc))
        if code >= 500:
            return ProviderError(f"HTTP {code}", transient=True, retry_after=_retry_after(exc))
        return ProviderError(f"HTTP {code}", transient=False)
    if names & _TIMEOUT_NAMES or isinstance(exc, asyncio.TimeoutError):
        return ProviderError("timeout", transient=True, timeout=True)
    if "DefaultCredentialsError" in names or "RefreshError" in names:
        return ProviderError("Google credentials are not available", transient=False)
    if names & _CONNECTION_NAMES or isinstance(exc, OSError):
        return ProviderError("connection error", transient=True)
    return ProviderError(type(exc).__name__, transient=False)


async def with_retries[T](call: Callable[[], Awaitable[T]], *, retries: int, backoff: float) -> tuple[T, int]:
    """Run `call`, retrying transient provider errors. Returns (result, retries used). BudgetExceeded and
    cancellation pass through untouched."""
    for attempt in range(retries + 1):
        try:
            return await call(), attempt
        except (BudgetExceeded, asyncio.CancelledError):
            raise
        except Exception as exc:
            error = map_exception(exc)
            if not error.transient or attempt == retries:
                if error is exc:
                    raise
                raise error from exc
            await asyncio.sleep(error.retry_after or backoff * 2**attempt)
    raise AssertionError("unreachable")


# --- provider -------------------------------------------------------------------------------------------------


class GoogleGenAIProvider:
    """ChatProvider over `client.aio.models.generate_content`. The client is created on first use, so constructing the
    gateway (readiness checks, tests) never touches credentials or the network."""

    name = "google"

    def __init__(self, settings: Settings, *, client: Any = None, meter: Any = None) -> None:
        self._settings = settings
        self._client = client
        self._meter = meter

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = build_client(self._settings, timeout_seconds=self._settings.llm_request_timeout_seconds)
        return self._client

    async def complete(self, request: ChatRequest) -> Completion:
        from google.genai import types

        system, contents = to_contents(request.messages)
        config = types.GenerateContentConfig(
            system_instruction=system, temperature=request.temperature, seed=request.seed,
            max_output_tokens=request.max_tokens,
            response_mime_type="application/json" if request.json_schema else None,
            response_json_schema=to_gemini_schema(request.json_schema) if request.json_schema else None,
            thinking_config=thinking_config(request.thinking_level),
        )
        try:
            response = await self.client.aio.models.generate_content(model=request.model, contents=contents, config=config)
        except BudgetExceeded:
            raise
        except Exception as exc:
            raise map_exception(exc) from exc
        check_blocked(response)
        if not (response.candidates or []):  # no candidate and no block reason: an empty reply, worth one more try
            raise ProviderError("empty response", transient=True)
        return Completion(text=visible_text(response), usage=usage_from(response.usage_metadata))


async def run_generation(
    api: Callable[[], Any], settings: Settings, *, meter: Any, backoff: float, capability: str, model: str, contents: Any,
    config: Any, stage: str, agent: str, prompt_version: str, estimate_usd: float,
    extract: Callable[[Any, Any], Any],
) -> tuple[Any, int, Usage | None]:
    """One metered, retried `generate_content` call for the non-chat capability adapters (image, speech, grounded
    research). `extract(response, record)` turns the response into the adapter's value and fills the CallRecord (images,
    audio seconds, grounded requests); a ProviderError it raises is final. Raises LLMError. Returns (value, retries, raw usage)."""
    from app.llm.budget import metered
    from app.llm.gateway import (
        budget_llm_error, failure_trace, provider_llm_error,
    )

    started = time.perf_counter()

    async def attempt() -> tuple[Any, Usage | None]:
        async with metered(
            meter, capability=capability, model=model, stage=stage, agent=agent, prompt_version=prompt_version,
            estimate_usd=estimate_usd,
        ) as record:
            try:
                response = await api().aio.models.generate_content(model=model, contents=contents, config=config)
            except Exception as exc:
                raise map_exception(exc) from exc
            check_blocked(response)
            record.usage = usage_from(response.usage_metadata)
            value = extract(response, record)
            return value, record.usage

    try:
        (value, usage), retries = await with_retries(
            attempt, retries=max(0, settings.llm_max_retries), backoff=backoff
        )
    except BudgetExceeded as exc:
        raise budget_llm_error(exc, failure_trace(stage, agent, "google", model, started, "BUDGET_EXCEEDED")) from exc
    except ProviderError as exc:
        code = "CONTENT_BLOCKED" if exc.blocked else "PROVIDER_TIMEOUT" if exc.timeout else "PROVIDER_ERROR"
        raise provider_llm_error(
            exc, failure_trace(stage, agent, "google", model, started, code), timeout_seconds=settings.llm_request_timeout_seconds
        ) from exc
    return value, retries, usage
