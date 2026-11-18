"""POST /api/v1/internal/digest/generate-weekly: Cloud Scheduler, authorised only by a Google OIDC ID token (a fake verifier here)."""

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.scheduler_auth import INVALID_TOKEN, NOT_CONFIGURED, get_verifier, google_oidc_verifier
from app.db import models as m
from app.db.session import read_session
from app.services import digest as digest_service
from tests.api.omnicult_support import API, client_for  # noqa: F401
from tests.api.test_crud import make_campaign, make_project

URL = f"{API}/internal/digest/generate-weekly"
ACCOUNT = "omnicult-scheduler@omnicult-app.iam.gserviceaccount.com"
AUDIENCE = "https://omnicult-api-671429087856.asia-south1.run.app"
NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
TOKEN = {"Authorization": "Bearer fake-google-id-token"}


class FakeVerifier:
    """Stands in for google-auth's id_token verification: no certificates, no network."""

    def __init__(self, claims: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self.claims, self.error, self.calls = claims, error, []

    def __call__(self, token: str, audience: str) -> dict[str, Any]:
        self.calls.append((token, audience))
        if self.error is not None:
            raise self.error
        assert self.claims is not None
        return self.claims


GOOD = {"email": ACCOUNT, "email_verified": True, "aud": AUDIENCE, "iss": "https://accounts.google.com"}


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHEDULER_SERVICE_ACCOUNT", ACCOUNT)
    monkeypatch.setenv("SCHEDULER_AUDIENCE", AUDIENCE)
    get_settings.cache_clear()
    monkeypatch.setattr(digest_service, "utcnow", lambda: NOW)


def use(app: FastAPI, verifier: FakeVerifier) -> FakeVerifier:
    app.dependency_overrides[get_verifier] = lambda: verifier
    return verifier


async def with_data(client: httpx.AsyncClient) -> str:
    """A live campaign carrying the Pulse sample and the sample comments, so there is something to report."""
    project = await make_project(client)
    cid = (await make_campaign(client, project["id"]))["id"]
    assert (await client.post(f"{API}/campaigns/{cid}/pulse/sample-dataset")).status_code == 200
    assert (await client.post(f"{API}/campaigns/{cid}/pulse/comments/sample")).status_code == 200
    return cid


# --- authorization --------------------------------------------------------------------------------------------------


async def test_every_call_is_refused_until_the_service_account_and_audience_are_configured(app: FastAPI, client_for: Any) -> None:
    sched = client_for({})
    verifier = use(app, FakeVerifier(GOOD))
    assert get_settings().scheduler_service_account is None and get_settings().scheduler_audience is None
    for headers in ({}, TOKEN, {"Authorization": "Bearer dev-alice"}):
        response = await sched.post(URL, headers=headers)
        assert response.status_code == 403 and response.json()["error"]["message"] == NOT_CONFIGURED, headers
    assert verifier.calls == [], "an unconfigured server never reaches the verifier"


@pytest.mark.parametrize("missing", ["SCHEDULER_SERVICE_ACCOUNT", "SCHEDULER_AUDIENCE"])
async def test_one_missing_setting_is_as_closed_as_both(app: FastAPI, client_for: Any, configured: None, monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    monkeypatch.setenv(missing, "  ")
    get_settings.cache_clear()
    verifier = use(app, FakeVerifier(GOOD))
    assert (await client_for({}).post(URL, headers=TOKEN)).status_code == 403 and verifier.calls == []


async def test_a_token_that_does_not_verify_or_names_another_identity_is_refused(app: FastAPI, client_for: Any, configured: None) -> None:
    client = client_for({})
    assert (await client.post(URL)).status_code == 401  # no token at all
    bad = use(app, FakeVerifier(error=ValueError("Token expired")))
    refused = await client.post(URL, headers=TOKEN)
    assert refused.status_code == 401 and refused.json()["error"]["message"] == INVALID_TOKEN  # the shared scheduler wording; no detail leaks
    assert bad.calls == [("fake-google-id-token", AUDIENCE)], "the token is checked against the configured audience"
    use(app, FakeVerifier(error=ValueError("Token expired")))
    assert (await client.post(URL, headers={"Authorization": "Bearer dev-alice"})).status_code == 401, "a dev or user token is not accepted"
    for claims in (
        {**GOOD, "email": "someone-else@omnicult-app.iam.gserviceaccount.com"},
        {**GOOD, "email_verified": False},
        {k: v for k, v in GOOD.items() if k != "email_verified"},
        {k: v for k, v in GOOD.items() if k != "email"},
    ):
        use(app, FakeVerifier(claims))
        assert (await client.post(URL, headers=TOKEN)).status_code == 403, claims
    use(app, FakeVerifier({**GOOD, "email": ACCOUNT.upper()}))
    assert (await client.post(URL, headers=TOKEN)).status_code == 200, "emails compare case-insensitively"


def test_the_real_verifier_rejects_a_token_that_is_not_a_google_id_token_without_the_network() -> None:
    for token in ("not-a-jwt", "a.b.c", ""):
        with pytest.raises(ValueError):
            google_oidc_verifier(token, AUDIENCE)


# --- what it does ---------------------------------------------------------------------------------------------------


async def test_it_generates_one_digest_per_active_campaign_and_is_idempotent_per_week(
    app: FastAPI, client: httpx.AsyncClient, client_for: Any, configured: None,
) -> None:
    use(app, FakeVerifier(GOOD))
    sched = client_for({})
    full = await with_data(client)
    empty_project = await make_project(client)
    empty = (await make_campaign(client, empty_project["id"]))["id"]
    archived_project = await make_project(client)
    await make_campaign(client, archived_project["id"])
    assert (await client.delete(f"{API}/projects/{archived_project['id']}")).status_code == 204

    first = await sched.post(URL, headers=TOKEN)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["week"]["label"] == "2026-W46" and body["week"]["start"] == "2026-11-09", "the last completed ISO week"
    assert (body["campaigns"], body["generated"], body["already_existed"], body["skipped_no_data"], body["failed"]) == (2, 1, 0, 1, 0)
    listing = (await client.get(f"{API}/campaigns/{full}/pulse/digests")).json()
    assert [i["week"]["label"] for i in listing["items"]] == ["2026-W46"] and listing["items"][0]["trigger"] == "scheduler"
    assert (await client.get(f"{API}/campaigns/{empty}/pulse/digests")).json()["items"] == [], "nothing to report: no empty digest is stored"
    digest = (await client.get(f"{API}/campaigns/{full}/pulse/digests/{listing['items'][0]['id']}")).json()
    assert digest["narrative"] is None and digest["content"]["pulse"]["available"] is True

    again = (await sched.post(URL, headers=TOKEN)).json()
    assert (again["generated"], again["already_existed"], again["skipped_no_data"], again["failed"]) == (0, 1, 1, 0), "safe to repeat"
    after = (await client.get(f"{API}/campaigns/{full}/pulse/digests/{listing['items'][0]['id']}")).json()
    assert after == digest, "a repeat leaves the stored digest untouched"

    earlier = await sched.post(URL, headers=TOKEN, json={"week_of": "2026-11-04"})
    assert earlier.json()["week"]["label"] == "2026-W45" and earlier.json()["generated"] == 1
    assert (await sched.post(URL, headers=TOKEN, json={"week_of": "2026-11-23"})).status_code == 422
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.PulseDigest)) == 2
        assert await s.scalar(select(func.count()).select_from(m.AiUsageEvent)) == 0, "the scheduled run calls no model"
        row = (await s.execute(select(m.PulseDigest).limit(1))).scalar_one()
        assert row.generated_by is None and row.trigger == "scheduler"
        audit = (await s.execute(select(m.AuditLog).where(m.AuditLog.action == "pulse.digest.generate").limit(1))).scalar_one()
        assert audit.actor_user_id is None and audit.detail["trigger"] == "scheduler"


async def test_one_failing_campaign_does_not_stop_the_others_and_makes_the_call_retry(
    app: FastAPI, client: httpx.AsyncClient, client_for: Any, configured: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    use(app, FakeVerifier(GOOD))
    sched = client_for({})
    good, bad = await with_data(client), await with_data(client)
    real = digest_service.build_content

    async def flaky(s: Any, sub: Any, week: Any, now: Any) -> Any:
        if str(sub.campaign.id) == bad:
            raise RuntimeError("boom")
        return await real(s, sub, week, now)

    monkeypatch.setattr(digest_service, "build_content", flaky)
    response = await sched.post(URL, headers=TOKEN)
    assert response.status_code == 500, "a failure is a non-2xx so Cloud Scheduler retries"
    body = response.json()
    assert (body["generated"], body["failed"]) == (1, 1) and body["failures"] == [{"campaign_id": bad, "error": "RuntimeError"}]
    assert len((await client.get(f"{API}/campaigns/{good}/pulse/digests")).json()["items"]) == 1
    monkeypatch.setattr(digest_service, "build_content", real)
    retry = await sched.post(URL, headers=TOKEN)
    assert retry.status_code == 200 and (retry.json()["generated"], retry.json()["already_existed"]) == (1, 1), "the retry only does what is missing"


async def test_the_internal_route_is_not_part_of_the_published_api(app: FastAPI, client: httpx.AsyncClient) -> None:
    assert "/api/v1/internal/digest/generate-weekly" not in app.openapi()["paths"]
