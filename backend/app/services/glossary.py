"""Brand Glossary (feature 4): per-brand terms with a language, a script, an approved spelling, a preferred translation,
pronunciation, protected and never-translate flags, and prohibited alternatives.

A glossary belongs to the brand (the project) and is read through any of its campaigns. Transcreate and Tweak Chips
consult it, and protected terms are checked in code on the regional copy and on its back-translation (app.studio.checks).
"""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas import versions as v
from app.schemas.common import ErrorDetail
from app.services.audit import record_audit
from app.services.common import conflict, not_found, paginate, touch
from app.services.versions import campaign_for
from app.studio.checks import script_check

SPELLING_MIN_SHARE = 0.5


def to_term(row: m.GlossaryTerm) -> v.GlossaryTerm:
    return v.GlossaryTerm(
        id=row.id, project_id=row.project_id, term=row.term, language=row.language, script=row.script,
        approved_spelling=row.approved_spelling, preferred_translation=row.preferred_translation,
        pronunciation=row.pronunciation, protected=row.protected, never_translate=row.never_translate,
        prohibited_alternatives=row.prohibited_alternatives, notes=row.notes, created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _invalid(field: str, message: str) -> ValidationFailed:
    return ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=field, message=message)])


def _check_spelling(script: str | None, spelling: str | None) -> None:
    """An approved spelling needs its script, and must actually be written in it (Unicode blocks)."""
    if spelling is None:
        return
    if script is None:
        raise _invalid("script", "Give the script of the approved spelling.")
    check = script_check(spelling, script, min_share=SPELLING_MIN_SHARE)
    if not check["ok"]:
        raise _invalid("approved_spelling", check["message"])


async def _known_language(s, language: str) -> None:  # type: ignore[no-untyped-def]
    if language != "*" and await s.get(m.Language, language) is None:
        raise _invalid("language", f"Unknown language {language}.")


async def create_term(user_id: UUID, campaign_id: UUID, body: v.GlossaryTermCreate) -> v.GlossaryTerm:
    async with session() as s, s.begin():
        _, project = await campaign_for(s, user_id, campaign_id, writable=True)
        await _known_language(s, body.language)
        _check_spelling(body.script, body.approved_spelling)
        now = utcnow()
        row = m.GlossaryTerm(
            id=uuid4(), project_id=project.id, term=body.term, term_key=body.term.casefold(), language=body.language,
            script=body.script, approved_spelling=body.approved_spelling, preferred_translation=body.preferred_translation,
            pronunciation=body.pronunciation, protected=body.protected, never_translate=body.never_translate,
            prohibited_alternatives=list(dict.fromkeys(body.prohibited_alternatives)), notes=body.notes, created_by=user_id,
            created_at=now, updated_at=now,
        )
        try:
            async with s.begin_nested():
                s.add(row)
                await s.flush()
        except IntegrityError:
            raise conflict("term", f"'{body.term}' already has an entry for language {body.language}.") from None
        await record_audit(s, action="studio.glossary_created", target_type="glossary_term", target_id=str(row.id),
                           workspace_id=project.workspace_id, actor_user_id=user_id, detail={"language": body.language})
        touch(project)
    return to_term(row)


async def list_terms(user_id: UUID, campaign_id: UUID, limit: int, offset: int, language: str | None = None) -> v.GlossaryTermPage:
    async with read_session() as s:
        _, project = await campaign_for(s, user_id, campaign_id)
        stmt = select(m.GlossaryTerm).where(m.GlossaryTerm.project_id == project.id)
        if language is not None:
            stmt = stmt.where(m.GlossaryTerm.language.in_([language, "*"]))
        rows, total = await paginate(s, stmt.order_by(m.GlossaryTerm.term_key, m.GlossaryTerm.language), limit, offset)
    return v.GlossaryTermPage(items=[to_term(r) for r in rows], limit=limit, offset=offset, total=total)


async def _row(s, project_id: UUID, term_id: UUID) -> m.GlossaryTerm:  # type: ignore[no-untyped-def]
    row = await s.get(m.GlossaryTerm, term_id)
    if row is None or row.project_id != project_id:
        raise not_found("Glossary term")
    return row


async def get_term(user_id: UUID, campaign_id: UUID, term_id: UUID) -> v.GlossaryTerm:
    async with read_session() as s:
        _, project = await campaign_for(s, user_id, campaign_id)
        return to_term(await _row(s, project.id, term_id))


async def update_term(user_id: UUID, campaign_id: UUID, term_id: UUID, body: v.GlossaryTermUpdate) -> v.GlossaryTerm:
    changes = body.model_dump(exclude_unset=True)
    async with session() as s, s.begin():
        _, project = await campaign_for(s, user_id, campaign_id, writable=True)
        row = await _row(s, project.id, term_id)
        for required in ("protected", "never_translate", "prohibited_alternatives"):
            if required in changes and changes[required] is None:
                raise _invalid(required, "May not be null.")
        for name, value in changes.items():
            setattr(row, name, list(dict.fromkeys(value)) if name == "prohibited_alternatives" else value)
        _check_spelling(row.script, row.approved_spelling)
        row.updated_at = utcnow()
        await s.flush()
        await record_audit(s, action="studio.glossary_updated", target_type="glossary_term", target_id=str(row.id),
                           workspace_id=project.workspace_id, actor_user_id=user_id, detail={"fields": sorted(changes)})
        touch(project)
    return to_term(row)


async def delete_term(user_id: UUID, campaign_id: UUID, term_id: UUID) -> None:
    """Remove an entry. Runs that already used it keep their own copy (a run records the entries it was given)."""
    async with session() as s, s.begin():
        _, project = await campaign_for(s, user_id, campaign_id, writable=True)
        row = await _row(s, project.id, term_id)
        await s.delete(row)
        await record_audit(s, action="studio.glossary_deleted", target_type="glossary_term", target_id=str(term_id),
                           workspace_id=project.workspace_id, actor_user_id=user_id, detail={"language": row.language})
        touch(project)
