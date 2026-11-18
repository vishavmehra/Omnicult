"""Google Gen AI provider: the only AI runtime behind the gateway (Vertex AI or the Gemini Developer API).

`GoogleGenAIProvider` implements the gateway's `ChatProvider` protocol. `build_client` is the one place a `genai.Client`
is created; tests inject a fake client (or patch this function), so nothing here needs the network to be tested.
Pydantic validation in the gateway stays authoritative: the JSON Schema sent to Gemini is only a hint, stripped of
keywords the API rejects. Errors are mapped to `ProviderError` (transient / timeout / blocked / permanent) and never carry
request or credential text.
"""

import asyncio
import json
import logging
import os
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import Settings
from app.llm.budget import BudgetExceeded
from app.llm.gateway import ChatRequest, Completion, ProviderError
from app.schemas.common import Usage

# JSON Schema keywords sent in `response_json_schema`. Everything else is dropped. `minItems` and `maxItems` are accepted by
# the API but not sent: Vertex answers a bare 400 INVALID_ARGUMENT ("Request contains an invalid argument.") to schemas whose
# nested arrays carry bounds (Quick Read: 6 participants x 4 point lists; X-Ray scenes). Reproduced live on gemini-3.8-flash:
# the request stayed a 400 with refs inlined, Optional unwrapped and integer bounds removed, and succeeded once the array
# bounds were removed too. Pydantic still enforces every bound on the reply.
_SCHEMA_KEYS = frozenset({
    "$id", "$defs", "$ref", "$anchor", "type", "format", "title", "description", "enum", "items", "prefixItems",
    "minimum", "maximum", "anyOf", "oneOf", "properties", "additionalProperties", "required",
})
_FORMATS = frozenset({"date-time", "date", "time"})
_SCHEMA_NODE_MAPS = ("properties", "$defs")  # {name: schema}
_SCHEMA_NODES = ("items", "additionalProperties", "prefixItems", "anyOf", "oneOf")  # schema or list of schemas

# finish reasons that mean the model declined or was filtered, as opposed to failing
BLOCKING_FINISH_REASONS = frozenset({
    "SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY", "IMAGE_PROHIBITED_CONTENT",
    "IMAGE_RECITATION",
})
log = logging.getLogger(__name__)
RETRY_AFTER_CAP_SECONDS = 10.0
INT32_MAX = 2**31 - 1  # Vertex rejects a `seed` outside int32 with a 400
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


_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_credentials: Any = None
_credentials_lock = threading.Lock()


def load_credentials() -> Any:
    """Application Default Credentials, loaded once per process and shared by every client.

    `google.auth.default()` runs the gcloud CLI to look up a project id whenever the credentials file holds none, which
    took 48 to 200 s on the development machine, and every new `genai.Client` repeated it (one per gateway, one per
    capability adapter). The project id is configuration (GOOGLE_CLOUD_PROJECT), so a user or service-account file is read
    directly (milliseconds); `default()` stays as the fallback for the metadata server (Cloud Run), workload identity,
    other file types and a missing file."""
    global _credentials
    with _credentials_lock:
        if _credentials is None:
            _credentials = _credentials_from_file() or _default_credentials()
        return _credentials


def _credentials_from_file() -> Any | None:
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or _well_known_credentials_path()
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        kind = json.load(handle).get("type")
    scopes = [_CLOUD_PLATFORM_SCOPE]
    if kind == "authorized_user":  # `gcloud auth application-default login`
        from google.oauth2 import credentials

        return credentials.Credentials.from_authorized_user_file(path, scopes=scopes)
    if kind == "service_account":
        from google.oauth2 import service_account

        return service_account.Credentials.from_service_account_file(path, scopes=scopes)
    return None


def _default_credentials() -> Any:
    import google.auth

    return google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])[0]


def _well_known_credentials_path() -> str | None:
    """Where `gcloud auth application-default login` writes the file (honours CLOUDSDK_CONFIG)."""
    try:
        from google.auth import _cloud_sdk

        return str(_cloud_sdk.get_application_default_credentials_path())
    except Exception:  # a private google-auth helper: without it, fall back to google.auth.default()
        return None


async def _in_daemon_thread(work: Callable[[], Any]) -> Any:
    """Run blocking `work` in a daemon thread and await its result. Unlike `asyncio.to_thread`, whose pool the loop joins when
    it closes (up to 300 s), a slow credential lookup (the gcloud CLI can take minutes) never holds up shutdown: a cancelled
    caller just stops waiting, and the thread ends with the process."""
    loop = asyncio.get_running_loop()
    done: asyncio.Future[Any] = loop.create_future()

    def settle(result: Any, error: Exception | None) -> None:
        if not done.done():  # the caller may have been cancelled meanwhile
            done.set_exception(error) if error else done.set_result(result)

    def run() -> None:
        try:
            outcome = (work(), None)
        except Exception as error:
            outcome = (None, error)
        try:
            loop.call_soon_threadsafe(settle, *outcome)
        except RuntimeError:  # the loop already closed: nobody is waiting
            pass

    threading.Thread(target=run, name="google-credentials", daemon=True).start()
    return await done


async def warm_credentials(settings: Settings) -> None:
    """Load the credentials in a daemon thread, never on the event loop. A no-op once loaded and for the API-key backend.
    Called from the app lifespan and again before a client is first built, so a request never waits on the lookup."""
    if settings.google_genai_backend == "vertex" and _credentials is None:
        await _in_daemon_thread(load_credentials)


def build_client(settings: Settings, *, location: str | None = None, timeout_seconds: float | None = None) -> Any:
    """The one `genai.Client` factory. `location` overrides GOOGLE_CLOUD_LOCATION (image models need `global`). Vertex
    clients receive the shared credentials, so creating a client never repeats the Application Default Credentials lookup."""
    from google import genai
    from google.genai import types

    options = types.HttpOptions(timeout=int(timeout_seconds * 1000)) if timeout_seconds else None
    if settings.google_genai_backend == "vertex":
        return genai.Client(
            vertexai=True, project=settings.google_cloud_project, location=location or settings.google_cloud_location,
            credentials=load_credentials(), http_options=options,
        )
    assert settings.gemini_api_key is not None
    return genai.Client(api_key=settings.gemini_api_key.get_secret_value(), http_options=options)


# --- request mapping ------------------------------------------------------------------------------------------


def to_gemini_schema(node: Any) -> Any:
    """Strip JSON Schema keywords Gemini rejects (lengths, patterns, defaults, array bounds, ...) and turn `const` into a
    one-value enum. Property names are never touched. The result is a hint; the gateway validates the reply against
    Pydantic, so dropping a bound here relaxes no check (the prompt and the schema text it carries still state the limit)."""
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


def to_int32(seed: int | None) -> int | None:
    """A sampling seed the API accepts: Vertex rejects values outside int32. The mapping is stable, so a seed stays reproducible."""
    return None if seed is None else seed % (INT32_MAX + 1)


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


def error_detail(exc: Any) -> str:
    """The API's own words for a rejection (its message plus any `fieldViolations` / `reason`), whitespace-collapsed and
    truncated. For logs only: it names a request field or a limit, and is never shown to a user."""
    parts = [str(getattr(exc, "message", "") or "")]
    body = getattr(exc, "details", None)
    error = body.get("error", body) if isinstance(body, dict) else {}
    for item in (error.get("details") or []) if isinstance(error, dict) else []:
        if not isinstance(item, dict):
            continue
        parts += [f"{v.get('field', '')}: {v.get('description', '')}" for v in item.get("fieldViolations") or [] if isinstance(v, dict)]
        parts.append(str(item.get("reason") or ""))
    return " ".join(" | ".join(x for x in parts if x).split())[:400]


def map_exception(exc: BaseException) -> ProviderError:
    """Gen AI SDK / transport exception -> ProviderError. The message is a status line, never the request or body."""
    if isinstance(exc, ProviderError):
        return exc
    names = {cls.__name__ for cls in type(exc).__mro__}
    code = getattr(exc, "code", None)
    if "APIError" in names and isinstance(code, int):
        # The status line and the API's own error text (a field name, a limit) go to the log only, truncated: the user-facing
        # message stays "HTTP <code>", and a 400 stays diagnosable without a reproduction.
        log.warning("provider error", extra={
            "provider_http": code, "provider_status": str(getattr(exc, "status", "") or "")[:40],
            "provider_detail": error_detail(exc),
        })
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
            system_instruction=system, temperature=request.temperature, seed=to_int32(request.seed),
            max_output_tokens=request.max_tokens,
            response_mime_type="application/json" if request.json_schema else None,
            response_json_schema=to_gemini_schema(request.json_schema) if request.json_schema else None,
            thinking_config=thinking_config(request.thinking_level),
        )
        try:
            if self._client is None:  # off the event loop; a credentials failure is mapped below like any provider error
                await warm_credentials(self._settings)
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
    extract: Callable[[Any, Any], Any], warm: bool = False,
) -> tuple[Any, int, Usage | None]:
    """One metered, retried `generate_content` call for the non-chat capability adapters (image, speech, grounded
    research). `extract(response, record)` turns the response into the adapter's value and fills the CallRecord (images,
    audio seconds, grounded requests); a ProviderError it raises is final. `warm` loads the credentials first (set it when
    the adapter has no injected client). Raises LLMError. Returns (value, retries, raw usage)."""
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
                if warm:  # the adapter builds its own client: load the credentials off the event loop first
                    await warm_credentials(settings)
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
