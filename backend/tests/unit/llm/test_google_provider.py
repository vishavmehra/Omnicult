"""GoogleGenAIProvider: request mapping, schema stripping, usage, blocks and error classification. No network."""

import asyncio

import httpx
import pytest
from google.genai import errors

from app.agents.voice import variants_schema
from app.llm import google
from app.llm.gateway import ChatRequest, ProviderError
from tests.unit.llm.genai_fakes import FakeClient, api_error, blocked_prompt, reply, settings


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
    schema = variants_schema(2).model_json_schema()  # a real agent schema: $defs, bounds, forbid-extra
    p, client = provider(reply("{}"))
    await p.complete(request(json_schema=schema))
    sent = client.calls[0].config
    assert sent.response_mime_type == "application/json"
    flat = repr(sent.response_json_schema)
    for rejected in ("maxLength", "minLength", "'default'", "'pattern'"):
        assert rejected not in flat
    assert sent.response_json_schema["properties"]["variants"]["maxItems"] == 2  # item bounds are supported and kept


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


def test_build_client_selects_vertex_or_the_developer_api():
    vertex = google.build_client(settings(google_cloud_location="asia-south1"), timeout_seconds=7)
    assert vertex.vertexai and vertex._api_client.project == "test-project" and vertex._api_client.location == "asia-south1"
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
