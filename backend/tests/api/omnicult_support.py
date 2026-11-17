"""Shared helpers for the Omnicult tenancy, evidence and region tests."""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.core.auth import dev_user_id
from app.core.config import get_settings
from app.db import models as m
from app.db.base import Base, utcnow
from app.db.session import dispose_engine, get_engine, read_session, session
from app.main import create_app
from app.reference.seed import seed_reference_data
from app.schemas.claims import ClaimDraft, ClaimScope, SourceRef
from app.services.identity import ensure_personal_workspace

API = "/api/v1"
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
CAROL = {"Authorization": "Bearer dev-carol"}


async def seed() -> None:
    async with session() as s, s.begin():
        await seed_reference_data(s)


async def workspace_of(label: str) -> UUID:
    """The personal workspace of a dev user (created on first use)."""
    user_id = dev_user_id(label)
    async with session() as s, s.begin():
        return await ensure_personal_workspace(s, user_id)


async def add_member(workspace_id: UUID, label: str, role: str) -> UUID:
    """Make a dev user a member of a workspace with the given role."""
    user_id = dev_user_id(label)
    async with session() as s, s.begin():
        await ensure_personal_workspace(s, user_id)  # also creates the users row
        existing = await s.scalar(select(m.WorkspaceMember).where(
            m.WorkspaceMember.workspace_id == workspace_id, m.WorkspaceMember.user_id == user_id))
        if existing is not None:
            existing.role = role
        else:
            s.add(m.WorkspaceMember(id=uuid4(), workspace_id=workspace_id, user_id=user_id, role=role, created_at=utcnow()))
    return user_id


def source(group: str, published: date | None = date(2026, 1, 1), *, source_type: str = "wikidata",
           identifier: str | None = None, excerpt: str | None = None, title: str | None = None) -> SourceRef:
    return SourceRef(
        source_type=source_type, source_identifier=identifier or f"{source_type}:{group}",  # type: ignore[arg-type]
        title=title or f"{group} source", published_at=published, retrieved_at=NOW, excerpt=excerpt,
        independence_group=group,
    )


def draft(value: Any, *, attribute: str = "major_festival", category: str = "festival", region: str | None = "IN-TN",
          subject: str | None = None, kind: str = "observed", sources: list[SourceRef] | None = None,
          text: str | None = None) -> ClaimDraft:
    return ClaimDraft(
        subject=subject or (f"region:{region}" if region else "entity:Q1"), attribute=attribute,
        category=category,  # type: ignore[arg-type]
        value=value, value_text=text or f"{attribute} is {value}", scope=ClaimScope(region_code=region),
        kind=kind,  # type: ignore[arg-type]
        sources=sources if sources is not None else [], retrieved_at=NOW,
    )


async def put_claims(workspace_id: UUID | None, drafts: list[ClaimDraft], *, mode: str = "live") -> Any:
    from app.services.claims import upsert_claims

    async with session() as s, s.begin():
        return await upsert_claims(s, drafts, workspace_id=workspace_id, mode=mode, now=NOW)


async def all_claims() -> list[m.Claim]:
    async with read_session() as s:
        return list((await s.execute(select(m.Claim))).scalars())


@pytest.fixture
async def seeded(app: FastAPI) -> FastAPI:
    await seed()
    return app


@pytest.fixture
async def client_for(app: FastAPI) -> AsyncIterator[Any]:
    """Factory for a client with explicit headers (the shared `client` fixture is bound to alice)."""
    transport = httpx.ASGITransport(app=app)
    clients: list[httpx.AsyncClient] = []

    def make(headers: dict[str, str]) -> httpx.AsyncClient:
        c = httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers)
        clients.append(c)
        return c

    yield make
    for c in clients:
        await c.aclose()


@pytest.fixture
async def firebase_app(test_settings: None, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    """The application in AUTH_MODE=firebase against a fresh database, with Google's signing keys replaced by a local key."""
    from tests.api.firebase_tokens import install_local_keys

    monkeypatch.setenv("AUTH_MODE", "firebase")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "omnicult-test")
    get_settings.cache_clear()
    install_local_keys(monkeypatch)
    await dispose_engine()
    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application
    await dispose_engine()
