"""No configured secret reaches an API response, an error body, or a log line (NFR-001/006).

Dummy secrets are injected through the environment. The real backend/.env values are also loaded
into memory and scanned for, in case any code path reads .env directly. Failure messages name the
variable and the location only; secret values are never printed.
"""

import logging
import traceback
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx
from dotenv import dotenv_values

from tests.api.omnicult_support import seed
from tests.integration._support import API, FakeProvider, auth, running_app, start_run, wait_for_run
from tests.integration.journey import create_demo, create_live_campaign, create_live_project

ELEMENTS = [{"id": "cta", "kind": "cta", "value": "Shop now", "language": "en", "script": "Latn"}]
TRANSCREATE = {"region_code": "IN-MH", "language": "mr", "element_ids": ["cta"]}

DUMMY_SECRETS = {
    "GEMINI_API_KEY": "AIza-qa-DUMMY-gemini-7f3a9c1e5b2d4f60",
    "YOUTUBE_API_KEY": "yt-qa-DUMMY-9e1c3a5b7d0f2468",
    "DATA_GOV_IN_API_KEY": "gov-qa-DUMMY-secret-4c6e8a0b2d1f3e57",
    "DATA_COMMONS_API_KEY": "dc-qa-DUMMY-secret-8b2d4f6a0c1e3957",
}
SECRET_NAMES = tuple(DUMMY_SECRETS)
PROVIDER_ECHO = "qa simulated provider detail"
_STANDARD_RECORD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "taskName"}


def real_env_secrets() -> dict[str, str]:
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return {}
    values = dotenv_values(env_file)
    return {f"real .env {name}": value for name in SECRET_NAMES if (value := values.get(name)) and len(value) >= 8}


def all_secrets() -> dict[str, str]:
    return {**DUMMY_SECRETS, **real_env_secrets()}


def scan(text: str, where: str, secrets: dict[str, str]) -> None:
    for name, value in secrets.items():
        if value in text:
            pytest.fail(f"{name} value leaked in {where}", pytrace=False)


def record_texts(records: list[logging.LogRecord]) -> Iterator[tuple[str, str]]:
    for record in records:
        yield f"log record {record.name}:{record.levelname}", record.getMessage()
        if record.exc_info:
            yield f"log traceback {record.name}", "".join(traceback.format_exception(*record.exc_info))
        if record.exc_text:
            yield f"log exc_text {record.name}", record.exc_text
        extras = {k: v for k, v in vars(record).items() if k not in _STANDARD_RECORD_ATTRS}
        if extras:
            yield f"log extras {record.name}", repr(extras)


class Recorder:
    """httpx response hook that keeps every status line, header block, and body seen by the client."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    async def __call__(self, response: httpx.Response) -> None:
        await response.aread()
        where = f"{response.request.method} {response.request.url.path} -> {response.status_code}"
        self.seen.append((f"{where} headers", "\n".join(f"{k}: {v}" for k, v in response.headers.items())))
        self.seen.append((f"{where} body", response.text))

    def scan(self, secrets: dict[str, str]) -> None:
        assert self.seen, "no responses were recorded"
        for where, text in self.seen:
            scan(text, where, secrets)


@pytest.fixture
def dummy_secrets(qa_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    for name, value in DUMMY_SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "qa-test-project")  # Vertex AI is configured; every call is faked
    return all_secrets()


ECHO = f"Incorrect API key provided: {DUMMY_SECRETS['GEMINI_API_KEY']} ({PROVIDER_ECHO})"


async def test_no_secret_in_basic_and_error_responses(
    dummy_secrets: dict[str, str], caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.DEBUG)
    recorder = Recorder()
    async with running_app() as app:
        app.client.event_hooks["response"].append(recorder)
        await app.client.get("/health")
        await app.client.get("/ready")
        await app.client.get(f"{API}/projects")  # 401
        await app.client.get(f"{API}/projects", headers={"Authorization": f"Bearer {DUMMY_SECRETS['DATA_GOV_IN_API_KEY']}"})
        await app.client.get(f"{API}/projects/not-a-uuid", headers=auth("qa-sec"))  # 422
        await app.client.post(f"{API}/projects", json={"name": "x"}, headers=auth("qa-sec"))  # 422
        await app.client.get(f"{API}/does-not-exist", headers=auth("qa-sec"))  # 404
    recorder.scan(dummy_secrets)
    for where, text in record_texts(caplog.records):
        scan(text, where, dummy_secrets)
    captured = capsys.readouterr()
    scan(captured.out + captured.err, "emitted log output", dummy_secrets)


async def test_no_secret_or_provider_detail_in_failed_live_runs(
    dummy_secrets: dict[str, str],
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Providers that echo credentials or internal details must not reach clients (README §3)."""
    caplog.set_level(logging.DEBUG)
    recorder = Recorder()
    alice = auth("qa-sec")
    with FakeProvider(401, {"error": {"message": ECHO}}):  # the provider answers 401 and echoes the key
        async with running_app() as app:
            app.client.event_hooks["response"].append(recorder)
            await seed()
            project = await create_live_project(app.client, alice)
            campaign = await create_live_campaign(app.client, alice, project.id)
            await app.client.post(
                f"{API}/campaigns/{campaign.id}/versions", headers=alice,
                json={"elements": ELEMENTS, "region_code": "IN-MH", "language": "en"},
            )
            accepted = await start_run(app.client, alice, f"{API}/campaigns/{campaign.id}/transcreate", TRANSCREATE, "transcreate")
            run = await wait_for_run(app.client, accepted.run_id, alice)
            assert run.status == "failed", f"{run.run_type} ended {run.status}"
            assert run.error is not None and run.error.code != "INTERNAL_ERROR", "failure must come from the provider path"
            assert PROVIDER_ECHO not in (run.error.message if run.error else ""), "raw provider detail in Run.error"
            await app.client.get(f"{API}/projects/{project.id}/runs", headers=alice)
            await app.client.get(f"{API}/projects/{project.id}/evidence", headers=alice)
    recorder.scan(dummy_secrets)
    for where, text in recorder.seen:
        if PROVIDER_ECHO in text:
            pytest.fail(f"raw provider error text reached a client in {where}", pytrace=False)
    captured = capsys.readouterr()
    scan(captured.out + captured.err, "emitted log output", dummy_secrets)


async def test_no_secret_in_demo_run_responses_or_logs(
    dummy_secrets: dict[str, str],
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal flows never even put a secret into a log record (stricter than formatter redaction).

    Live credentials are configured on purpose: a demo project must still never call a provider.
    """
    caplog.set_level(logging.DEBUG)
    recorder = Recorder()
    with FakeProvider(500, {"error": {"message": "demo must not call out"}}) as provider, respx.mock(assert_all_called=False) as network:
        network.route().mock(side_effect=httpx.ConnectError("qa: demo runs must not call out"))
        async with running_app() as app:
            app.client.event_hooks["response"].append(recorder)
            headers = auth("qa-sec")
            await seed()
            journey = await create_demo(app.client, headers, check=False)
            await app.client.post(
                f"{API}/campaigns/{journey.campaign_id}/versions", headers=headers,
                json={"elements": ELEMENTS, "region_code": "IN-MH", "language": "en"},
            )
            accepted = await start_run(app.client, headers, f"{API}/campaigns/{journey.campaign_id}/transcreate", TRANSCREATE, "transcreate")
            run = await wait_for_run(app.client, accepted.run_id, headers)
            assert run.status == "completed", f"the demo transcreate run ended {run.status}"
            await app.client.get(f"{API}/projects/{journey.project_id}/runs", headers=headers)
        assert not network.calls, f"demo journey made {len(network.calls)} outbound HTTP call(s); demo must never call out"
        assert not provider.requests, f"demo journey called the LLM provider: {provider.requests}"
    recorder.scan(dummy_secrets)
    for where, text in record_texts(caplog.records):
        scan(text, where, dummy_secrets)
    captured = capsys.readouterr()
    scan(captured.out + captured.err, "emitted log output", dummy_secrets)
