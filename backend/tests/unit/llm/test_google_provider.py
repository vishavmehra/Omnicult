"""GoogleGenAIProvider: request mapping, schema stripping, usage, blocks and error classification. No network."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors
from pydantic import BaseModel, ConfigDict, Field

from app.llm import google
from app.llm.gateway import ChatRequest, ProviderError
from tests.unit.llm.genai_fakes import FakeClient, api_error, blocked_prompt, reply, settings


class _Variant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(default="x", min_length=1, max_length=100, pattern="^.+$")


class _Variants(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variants: list[_Variant] = Field(min_length=1, max_length=3)


def request(**overrides) -> ChatRequest:
    values = dict(
        model="gemini-3.8-flash", messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        temperature=0.2, seed=7, max_tokens=300, json_schema=None, prompt_version="p-v1",
    )
    return ChatRequest(**(values | overrides))


def provider(*script) -> tuple[google.GoogleGenAIProvider, FakeClient]:
    client = FakeClient(list(script))
    return google.GoogleGenAIProvider(settings(), client=client), client


async def test_messages_map_to_system_instruction_and_model_role():
    messages = [
        {"role": "system", "content": "rule one"}, {"role": "system", "content": "rule two"},
        {"role": "user", "content": [{"type": "text", "text": "look"},
                                     {"type": "image", "mime_type": "image/png", "data": b"\x89PNG"}]},
        {"role": "assistant", "content": ""}, {"role": "user", "content": "again"},
    ]
    p, client = provider(reply("ok"))
    await p.complete(request(messages=messages))
    sent = client.calls[0]
    assert sent.config.system_instruction == "rule one\n\nrule two"
    assert [c.role for c in sent.contents] == ["user", "model", "user"]
    assert sent.contents[0].parts[0].text == "look" and sent.contents[0].parts[1].inline_data.data == b"\x89PNG"
    assert sent.contents[0].parts[1].inline_data.mime_type == "image/png"
    assert sent.contents[1].parts[0].text == "(no output)"  # Gemini rejects empty text parts
    assert (sent.config.temperature, sent.config.seed, sent.config.max_output_tokens) == (0.2, 7, 300)
    assert sent.config.response_mime_type is None and sent.config.response_json_schema is None


async def test_json_schema_is_sent_stripped_of_keywords_gemini_rejects():
    schema = _Variants.model_json_schema()  # like the agents' schemas: $defs, bounds, forbid-extra
    p, client = provider(reply("{}"))
    await p.complete(request(json_schema=schema))
    sent = client.calls[0].config
    assert sent.response_mime_type == "application/json"
    flat = repr(sent.response_json_schema)
    for rejected in ("maxLength", "minLength", "'default'", "'pattern'"):
        assert rejected not in flat
    assert "maxItems" not in flat and "minItems" not in flat  # Vertex answers 400 to bounded nested arrays; Pydantic enforces them
    assert sent.response_json_schema["properties"]["variants"]["type"] == "array"


def test_schema_stripping_keeps_property_names_and_rewrites_const():
    schema = {
        "type": "object", "additionalProperties": False, "required": ["default", "kind"],
        "properties": {
            "default": {"type": "string", "maxLength": 5, "pattern": "^a", "default": "x"},  # a property NAMED default
            "kind": {"const": "a", "type": "string"},
            "id": {"type": "string", "format": "uuid"}, "when": {"type": "string", "format": "date-time"},
            "ref": {"$ref": "#/$defs/Item", "description": "dropped beside a $ref"},
        },
        "$defs": {"Item": {"type": "integer", "minimum": 1, "exclusiveMinimum": 0, "multipleOf": 2}},
    }
    out = google.to_gemini_schema(schema)
    assert set(out["properties"]) == {"default", "kind", "id", "when", "ref"} and out["required"] == ["default", "kind"]
    assert out["properties"]["default"] == {"type": "string"}
    assert out["properties"]["kind"] == {"enum": ["a"], "type": "string"}
    assert out["properties"]["id"] == {"type": "string"} and out["properties"]["when"]["format"] == "date-time"
    assert out["properties"]["ref"] == {"$ref": "#/$defs/Item"}
    assert out["$defs"]["Item"] == {"type": "integer", "minimum": 1}
    assert out["additionalProperties"] is False


async def test_usage_includes_thinking_tokens_as_output():
    p, _ = provider(reply("ok", prompt=100, out=20, thoughts=30))
    completion = await p.complete(request())
    u = completion.usage
    assert (u.input_tokens, u.output_tokens, u.thinking_tokens, u.total_tokens) == (100, 50, 30, 150)
    p, _ = provider(reply("ok", prompt=None, out=None))
    assert (await p.complete(request())).usage is None


async def test_thoughts_are_not_part_of_the_answer():
    from google.genai import types

    response = reply("answer")
    response.candidates[0].content.parts.insert(0, types.Part(text="internal reasoning", thought=True))
    p, _ = provider(response)
    assert (await p.complete(request())).text == "answer"


@pytest.mark.parametrize("response", [
    blocked_prompt("SAFETY"), blocked_prompt("PROHIBITED_CONTENT"), reply("", finish="SAFETY"),
    reply("partial", finish="RECITATION"), reply("", finish="IMAGE_SAFETY"),
])
async def test_safety_blocks_are_blocked_provider_errors(response):
    p, client = provider(response)
    with pytest.raises(ProviderError) as caught:
        await p.complete(request())
    assert caught.value.blocked and not caught.value.transient and len(client.calls) == 1


async def test_a_block_logs_its_reason_and_flagged_categories_but_never_the_text(caplog):
    from google.genai import types

    answer = reply("secret answer text", finish="SAFETY")
    answer.candidates[0].safety_ratings = [
        types.SafetyRating(category="HARM_CATEGORY_HARASSMENT", probability="HIGH", blocked=True),
        types.SafetyRating(category="HARM_CATEGORY_HATE_SPEECH", probability="NEGLIGIBLE", blocked=False),
    ]
    p, _ = provider(answer)
    with caplog.at_level("WARNING", logger="app.llm.google"), pytest.raises(ProviderError):
        await p.complete(request())
    record = next(r for r in caplog.records if r.getMessage() == "provider blocked")
    assert record.block_reason == "SAFETY" and record.flagged_categories == ["HARM_CATEGORY_HARASSMENT"]
    assert "secret answer text" not in repr(vars(record))
    p, _ = provider(blocked_prompt("PROHIBITED_CONTENT"))
    with caplog.at_level("WARNING", logger="app.llm.google"), pytest.raises(ProviderError):
        await p.complete(request())
    assert [r.block_reason for r in caplog.records if r.getMessage() == "provider blocked"] == ["SAFETY", "PROHIBITED_CONTENT"]


async def test_empty_reply_without_a_reason_is_transient_and_max_tokens_is_not_a_block():
    from google.genai import types

    p, _ = provider(types.GenerateContentResponse(candidates=[]))
    with pytest.raises(ProviderError) as caught:
        await p.complete(request())
    assert caught.value.transient and not caught.value.blocked
    p, _ = provider(reply('{"a":', finish="MAX_TOKENS"))
    assert (await p.complete(request())).text == '{"a":'  # truncated JSON goes to the gateway's repair, not to an error


@pytest.mark.parametrize("error, transient, timeout", [
    (api_error(429, "RESOURCE_EXHAUSTED"), True, False), (api_error(500), True, False), (api_error(503), True, False),
    (api_error(504, "DEADLINE_EXCEEDED"), True, True), (api_error(408), True, True),
    (api_error(400, "INVALID_ARGUMENT"), False, False), (api_error(401), False, False), (api_error(403), False, False),
    (api_error(404, "NOT_FOUND"), False, False),
    (httpx.ReadTimeout("slow"), True, True), (httpx.ConnectError("down"), True, False), (asyncio.TimeoutError(), True, True),
    (ValueError("anything else"), False, False),
])
async def test_errors_are_classified_and_carry_no_provider_text(error, transient, timeout):
    p, _ = provider(error)
    with pytest.raises(ProviderError) as caught:
        await p.complete(request())
    assert (caught.value.transient, caught.value.timeout, caught.value.blocked) == (transient, timeout, False)
    assert "detail that must never reach a user" not in str(caught.value)


async def test_retry_after_is_read_from_header_or_retry_info_and_capped():
    p, _ = provider(api_error(429, retry_after="3"))
    with pytest.raises(ProviderError) as caught:
        await p.complete(request())
    assert caught.value.retry_after == 3.0
    p, _ = provider(api_error(429, retry_after="120"))
    with pytest.raises(ProviderError) as caught:
        await p.complete(request())
    assert caught.value.retry_after == google.RETRY_AFTER_CAP_SECONDS
    body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "m",
                      "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "4s"}]}}
    p, _ = provider(errors.ClientError(429, body))
    with pytest.raises(ProviderError) as caught:
        await p.complete(request())
    assert caught.value.retry_after == 4.0


def test_configuration_per_backend():
    assert google.is_configured(settings())
    assert not google.is_configured(settings(google_cloud_project=None))
    assert google.is_configured(settings(google_genai_backend="gemini_api", gemini_api_key="k", google_cloud_project=None))
    assert not google.is_configured(settings(google_genai_backend="gemini_api", gemini_api_key=None))


def test_client_is_built_lazily_and_per_backend(monkeypatch):
    built = []
    monkeypatch.setattr(google, "build_client", lambda s, **kw: built.append((s.google_genai_backend, kw)) or FakeClient())
    p = google.GoogleGenAIProvider(settings())
    assert built == []  # constructing the provider (readiness checks) never touches credentials
    assert isinstance(p.client, FakeClient) and p.client is p.client and len(built) == 1
    assert built[0][1] == {"timeout_seconds": 5}


def test_build_client_selects_vertex_or_the_developer_api(monkeypatch):
    shared = object()
    monkeypatch.setattr(google, "load_credentials", lambda: shared)  # never the real Application Default Credentials
    vertex = google.build_client(settings(google_cloud_location="asia-south1"), timeout_seconds=7)
    assert vertex.vertexai and vertex._api_client.project == "test-project" and vertex._api_client.location == "asia-south1"
    assert vertex._api_client._credentials is shared  # so the SDK never runs google.auth.default() itself
    keyed = google.build_client(settings(google_genai_backend="gemini_api", gemini_api_key="k", google_cloud_project=None))
    assert not keyed.vertexai


async def test_with_retries_retries_transient_and_passes_budget_errors_through():
    from app.llm.budget import BudgetExceeded

    attempts = iter([api_error(503), "ok"])

    async def flaky():
        item = next(attempts)
        if isinstance(item, Exception):
            raise item
        return item

    assert await google.with_retries(flaky, retries=1, backoff=0) == ("ok", 1)

    async def over():
        raise BudgetExceeded("run", 1.0, 1.0, 0.1)

    with pytest.raises(BudgetExceeded):
        await google.with_retries(over, retries=3, backoff=0)


# --- credentials: one lookup per process, off the event loop -----------------------------------------------------


@pytest.fixture
def fresh_credentials(monkeypatch):
    monkeypatch.setattr(google, "_credentials", None)
    lookups: list[str] = []
    monkeypatch.setattr(google, "_credentials_from_file", lambda: lookups.append("file") or None)
    monkeypatch.setattr(google, "_default_credentials", lambda: lookups.append("default") or object())
    return lookups


def test_credentials_are_looked_up_once_and_shared_by_every_client(fresh_credentials):
    first = google.load_credentials()
    assert google.load_credentials() is first and google.load_credentials() is first
    clients = [google.build_client(settings(), timeout_seconds=5) for _ in range(3)]  # gateways and adapters each build one
    assert all(c._api_client._credentials is first for c in clients)
    assert fresh_credentials == ["file", "default"]  # one lookup, however many clients


async def test_warm_credentials_runs_in_a_worker_thread_once_and_skips_the_api_key_backend(fresh_credentials, monkeypatch):
    import threading

    threads: list[int] = []
    monkeypatch.setattr(google, "_default_credentials", lambda: threads.append(threading.get_ident()) or object())
    await google.warm_credentials(settings(google_genai_backend="gemini_api", gemini_api_key="k", google_cloud_project=None))
    assert threads == []  # nothing to load for an API key
    await asyncio.gather(google.warm_credentials(settings()), google.warm_credentials(settings()))
    await google.warm_credentials(settings())
    assert len(threads) == 1 and threads[0] != threading.get_ident()  # one lookup, never on the event loop's thread


async def test_a_slow_credential_lookup_never_holds_up_shutdown_and_a_failure_reaches_the_caller(fresh_credentials, monkeypatch):
    import threading

    from google.auth.exceptions import DefaultCredentialsError

    release = threading.Event()
    monkeypatch.setattr(google, "_default_credentials", lambda: release.wait(30) or object())
    waiting = asyncio.create_task(google.warm_credentials(settings()))
    await asyncio.sleep(0.05)
    waiting.cancel()  # shutdown: the caller stops waiting while the lookup (the gcloud CLI, minutes) is still running
    with pytest.raises(asyncio.CancelledError):
        await waiting
    (lookup,) = [t for t in threading.enumerate() if t.name == "google-credentials"]
    assert lookup.is_alive() and lookup.daemon  # a daemon: the loop's executor shutdown and interpreter exit never join it
    release.set()
    lookup.join(5)
    assert not lookup.is_alive()

    def missing():
        raise DefaultCredentialsError("no credentials")

    monkeypatch.setattr(google, "_credentials", None)
    monkeypatch.setattr(google, "_default_credentials", missing)
    with pytest.raises(DefaultCredentialsError):
        await google.warm_credentials(settings())


async def test_the_first_request_warms_credentials_before_it_builds_a_client(monkeypatch):
    order: list[str] = []

    async def warm(_settings):
        order.append("warm")

    def build(_settings, **_kw):
        order.append("build")
        return FakeClient([reply("ok"), reply("ok")])

    monkeypatch.setattr(google, "warm_credentials", warm)
    monkeypatch.setattr(google, "build_client", build)
    p = google.GoogleGenAIProvider(settings())
    await p.complete(request())
    await p.complete(request())
    assert order == ["warm", "build"]  # the client, once built, is reused: no second lookup


async def test_missing_credentials_are_a_typed_final_provider_error_not_a_raw_exception(monkeypatch):
    from google.auth.exceptions import DefaultCredentialsError

    from app.llm.gateway import LLMError, LLMGateway

    async def no_credentials(_settings):
        raise DefaultCredentialsError("could not find default credentials")

    monkeypatch.setattr(google, "warm_credentials", no_credentials)
    with pytest.raises(ProviderError) as caught:
        await google.GoogleGenAIProvider(settings()).complete(request())
    assert not caught.value.transient and str(caught.value) == "Google credentials are not available"

    from app.llm.smoke import SmokeOut

    with pytest.raises(LLMError) as failed:  # through the gateway: a typed, non-retryable PROVIDER_ERROR (never a 500)
        await LLMGateway(settings(), backoff_seconds=0).generate_structured(
            task="extraction", stage="s", agent="a", system="s", user="u", schema=SmokeOut, prompt_version="p")
    assert failed.value.code == "PROVIDER_ERROR" and failed.value.retryable is False


def test_credentials_file_types_are_read_directly(tmp_path, monkeypatch):
    import json

    path = tmp_path / "adc.json"
    path.write_text(json.dumps({"type": "authorized_user", "client_id": "i", "client_secret": "s", "refresh_token": "r",
                                "quota_project_id": "billing-project"}))
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(path))
    creds = google._credentials_from_file()
    assert creds.quota_project_id == "billing-project" and "cloud-platform" in creds.scopes[0]
    path.write_text(json.dumps({"type": "external_account"}))
    assert google._credentials_from_file() is None  # other types fall back to google.auth.default()
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "missing.json"))
    assert google._credentials_from_file() is None


# --- request shape and error detail --------------------------------------------------------------------------------


def test_seed_is_mapped_into_the_int32_range_vertex_accepts():
    assert google.to_int32(None) is None and google.to_int32(42) == 42
    assert 0 <= google.to_int32(2**31) < 2**31 and google.to_int32(2**40 + 7) == google.to_int32(2**40 + 7)  # stable


async def test_a_huge_seed_reaches_the_api_as_int32():
    p, client = provider(reply("ok"))
    await p.complete(request(seed=2**40 + 7))
    assert client.calls[0].config.seed == (2**40 + 7) % 2**31


def test_a_rejection_logs_the_apis_own_words_but_the_user_message_stays_a_status_line(caplog):
    body = {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "Request contains an invalid argument.",
                      "details": [{"@type": "type.googleapis.com/google.rpc.BadRequest",
                                   "fieldViolations": [{"field": "generation_config.response_json_schema", "description": "too many states"}]}]}}
    error = errors.ClientError(400, body, SimpleNamespace(headers={}))
    with caplog.at_level("WARNING", logger="app.llm.google"):
        mapped = google.map_exception(error)
    assert str(mapped) == "HTTP 400" and not mapped.transient
    record = next(r for r in caplog.records if getattr(r, "provider_http", None) == 400)
    assert record.provider_status == "INVALID_ARGUMENT"
    assert "too many states" in record.provider_detail and "generation_config.response_json_schema" in record.provider_detail
    assert len(google.error_detail(error)) <= 400


async def test_the_app_loads_google_credentials_in_the_background_only_when_google_is_configured(monkeypatch):
    from app import main
    from app.llm import google

    loads: list[str] = []

    async def warm(configured):
        loads.append(configured.google_cloud_project)

    monkeypatch.setattr(google, "warm_credentials", warm)
    monkeypatch.setattr(main, "get_settings", lambda: settings(google_cloud_project=None))
    await main.warm_google_credentials()
    assert loads == []  # no project: nothing to load, no lookup
    monkeypatch.setattr(main, "get_settings", lambda: settings(google_cloud_project="p"))
    await main.warm_google_credentials()
    assert loads == ["p"]

    async def broken(configured):
        raise RuntimeError("no credentials on this machine")

    monkeypatch.setattr(google, "warm_credentials", broken)
    await main.warm_google_credentials()  # a startup failure is logged, never raised: the first call reports it
