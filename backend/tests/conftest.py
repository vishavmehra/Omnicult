"""Shared fixtures: isolated settings, a fresh SQLite database per test, and an ASGI client.

Provider credentials are blanked so no test can reach a paid API, even when backend/.env
holds real keys (environment variables take precedence over the .env file).
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from google.auth.exceptions import DefaultCredentialsError

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import dispose_engine, get_engine
from app.main import create_app
from app.schemas.runs import TERMINAL_RUN_STATUSES

BLANKED = (
    "GOOGLE_CLOUD_PROJECT", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "YOUTUBE_API_KEY",
    "BIGQUERY_PROJECT", "DATA_GOV_IN_API_KEY",
)


@pytest.fixture(autouse=True)
def fresh_usage_sink() -> Iterator[None]:
    """The default usage sink is process-wide (budgets read it); give every test an empty one."""
    from app.llm.budget import InMemoryUsageSink, get_default_usage_sink, set_default_usage_sink

    original = get_default_usage_sink()
    set_default_usage_sink(InMemoryUsageSink())
    yield
    set_default_usage_sink(original)


class FakeCredentials:
    """Stands in for Application Default Credentials. It holds no token and cannot be refreshed, so a Google call that gets as
    far as authenticating fails at once with the error a missing credential gives, before any socket is opened."""

    token = None
    expired = True
    valid = False

    def refresh(self, _request: Any) -> None:
        raise DefaultCredentialsError("tests never use real Google credentials")


@pytest.fixture(autouse=True)
def no_real_google_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reads this machine's Application Default Credentials, runs the gcloud CLI, or reaches Google with the
    developer's token. A test that configures a Google project (to run live workflows against fake models) makes the app load
    credentials at startup, and `google.auth.default()` shells out to gcloud (minutes). Every credential lookup now ends in
    FakeCredentials, which fails at once. The credential cache is process-wide, so it starts empty for every test."""
    from app.llm import google

    monkeypatch.setattr(google, "_credentials", None)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)  # a test that reads a credentials file brings its own
    monkeypatch.setattr(google, "_well_known_credentials_path", lambda: None)  # gcloud's file in the user's profile
    monkeypatch.setattr(google, "_default_credentials", FakeCredentials)
    monkeypatch.setattr("google.auth.default", lambda *_, **__: (FakeCredentials(), "test-project"))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "postgres: opt-in checks against a real Postgres (OMNICULT_TEST_POSTGRES_URL)")


def auth(label: str) -> dict[str, str]:
    """Headers for a dev-mode user; different labels are different users."""
    return {"Authorization": f"Bearer dev-{label}"}


ALICE, BOB = auth("alice"), auth("bob")


@pytest.fixture
def test_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[None]:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("ASSET_STORAGE_BACKEND", "database")  # tests never reach the real Storage bucket
    monkeypatch.setenv("DEMO_SEED", "legacy")  # the older workflow tests are written for the Northstar seed; Aamod tests opt in
    for name in BLANKED:
        monkeypatch.setenv(name, "")
    # A zero-dimension embedding space is not usable, which switches the post-run search indexing off. Tests that configure a
    # Google project to run live workflows would otherwise start real embedding calls that outlive the test (search tests bring
    # their own fake embedder).
    monkeypatch.setenv("GEMINI_EMBEDDING_DIMENSIONS", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def settle_background_runs(timeout: float = 5.0) -> None:
    """Let runs still in flight finish on their own before the app shuts down. A run keeps working after it reads as finished
    (its search indexing comes last), and cancelling it in the middle of a query leaves SQLAlchemy a connection to terminate
    that the aiosqlite worker never answers: the event loop's close then waits for it forever."""
    from app.services import audience, runs

    with contextlib.suppress(TimeoutError):
        async with asyncio.timeout(timeout):
            await runs.wait_idle()
            await audience.wait_idle()


@pytest.fixture
async def app(test_settings: None) -> AsyncIterator[FastAPI]:
    """The application with a migrated-equivalent schema, run through its lifespan like uvicorn does."""
    await dispose_engine()
    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application
        await settle_background_runs()
    await dispose_engine()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=ALICE) as c:
        yield c


async def wait_for_run(client: httpx.AsyncClient, run_id: str, timeout: float = 10.0, **kwargs: Any) -> dict[str, Any]:
    """Poll GET /runs/{id} until the run reaches a terminal status."""
    async with asyncio.timeout(timeout):
        while True:
            response = await client.get(f"/api/v1/runs/{run_id}", **kwargs)
            assert response.status_code == 200, response.text
            run = response.json()
            if run["status"] in TERMINAL_RUN_STATUSES:
                return run
            await asyncio.sleep(0.02)
