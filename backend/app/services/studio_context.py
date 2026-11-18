"""What Tweak Chips and Transcreate read before they call a model: the region's claims, the brand glossary, the gateway.

All reads are workspace-scoped: a claim is visible when it is shared (`workspace_id` NULL) or owned by the project's
workspace, in the project's mode (demo fixtures never mix with live data), and not rejected or superseded.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, ValidationFailed
from app.db import models as m
from app.llm.gateway import LLMError, LLMGateway
from app.schemas.common import ErrorDetail
from app.services.claims import LIVE_STATUSES

# Categories first that most affect copy: language and script, then festivals, colour and symbols, humour, family, custom.
CLAIM_PRIORITY = (
    "language", "script", "festival", "moment", "colour", "symbol", "humour", "family", "custom", "food", "sensitivity",
    "media", "demographic", "trend",
)
CLAIM_LIMIT = 24
LLM_STATUS = {"PROVIDER_TIMEOUT": 504, "RATE_LIMITED": 429, "BUDGET_EXCEEDED": 429, "PROVIDER_NOT_CONFIGURED": 503}


async def region_named(s: AsyncSession, region_code: str, field: str = "region_code") -> m.Region:
    region = await s.scalar(select(m.Region).where(m.Region.code == region_code, m.Region.is_active))
    if region is None:
        raise ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=field, message=f"Unknown region {region_code}.")])
    return region


async def language_named(s: AsyncSession, code: str, field: str = "language") -> m.Language:
    language = await s.get(m.Language, code)
    if language is None or not language.is_active:
        raise ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=field, message=f"Unknown language {code}.")])
    return language


async def region_claims(s: AsyncSession, project: m.Project, region: m.Region, limit: int = CLAIM_LIMIT) -> list[dict[str, Any]]:
    """A digest of the region's claims for a prompt: [{id, handle, category, statement, kind, confidence}], most relevant
    categories first. The handle (C1, C2, ...) is what a model cites; the id stays server side."""
    stmt = select(m.Claim).where(
        or_(m.Claim.workspace_id == project.workspace_id, m.Claim.workspace_id.is_(None)),
        m.Claim.region_id == region.id, m.Claim.mode == project.mode, m.Claim.status.in_(LIVE_STATUSES),
    ).order_by(m.Claim.category, m.Claim.attribute, m.Claim.created_at, m.Claim.id)
    rows = list((await s.execute(stmt)).scalars())
    rank = {category: i for i, category in enumerate(CLAIM_PRIORITY)}
    rows.sort(key=lambda c: rank.get(c.category, len(rank)))  # stable: ties keep their database order
    return [
        {"id": str(c.id), "handle": f"C{i}", "category": c.category, "statement": c.value_text, "kind": c.kind,
         "confidence": c.confidence}
        for i, c in enumerate(rows[:limit], 1)
    ]


async def glossary_entries(s: AsyncSession, project_id: UUID, language: str | None) -> list[dict[str, Any]]:
    """The project's glossary entries for a language, plus the `*` (every language) entries, as plain dicts."""
    wanted = ["*"] + ([language] if language else [])
    rows = (await s.execute(
        select(m.GlossaryTerm).where(m.GlossaryTerm.project_id == project_id, m.GlossaryTerm.language.in_(wanted))
        .order_by(m.GlossaryTerm.term_key, m.GlossaryTerm.language)
    )).scalars()
    return [
        {"term": g.term, "language": g.language, "script": g.script, "approved_spelling": g.approved_spelling,
         "preferred_translation": g.preferred_translation, "pronunciation": g.pronunciation, "protected": g.protected,
         "never_translate": g.never_translate, "prohibited_alternatives": list(g.prohibited_alternatives), "notes": g.notes}
        for g in rows
    ]


def gateway_for(mode: str) -> LLMGateway:
    """The model gateway for a project: fixtures in demo mode (no network), the configured provider in live mode."""
    from app import workflows  # resolved at call time, so tests can substitute the workflow dependencies

    return workflows.build_workflow_deps(mode, get_settings()).llm  # type: ignore[arg-type]


def llm_failure(exc: LLMError) -> AppError:
    """A typed model failure becomes its contract error code, never a 500."""
    error = AppError(exc.message)
    error.code = exc.code
    error.status_code = LLM_STATUS.get(exc.code, 502)
    return error
