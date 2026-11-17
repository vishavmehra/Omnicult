"""Proof Report v2: deterministic snapshots, versioning, and exports (JSON, Markdown, PDF).

`create_report` builds a `SectionContext`, runs the registered section providers (`proof_sections`), and stores the
result as the campaign's next snapshot. A snapshot is never changed; a new one gets the next `version_number`. The
`content_sha256` covers the sections, the campaign content version and the regions, so equal inputs give an equal hash.

Exports are generated from the stored snapshot. `export_inline` returns the bytes for an authenticated request;
`create_export` also stores them through the blob store (`app.db.blobs`) and returns a short-lived link whose token is
random, unguessable and stored only as a hash. Markdown exists only as an export format generated at request time.
"""

import asyncio
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from app.core.config import get_settings
from app.core.errors import Conflict, NotFound
from app.db import blobs
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.schemas.proof import (
    AssemblyInfo,
    MissingSection,
    ProofExport,
    ProofReport,
    ProofReportCreate,
    ProofReportPage,
    ProofReportSummary,
    ProofSectionInfo,
    SectionBase,
)
from app.services.audit import record_audit
from app.services.common import get_owned, paginate, touch
from app.services.proof_pdf import to_pdf
from app.services.proof_render import report_blocks, to_markdown
from app.services.proof_sections import (
    KIND_LEGEND,
    LEGAL_NOTICE,
    REGISTRY_VERSION,
    assemble,
    build_context,
    is_wired,
    ordered_specs,
)

API = "/api/v1"
FORMATS = {
    "json": ("application/json", "json"),
    "markdown": ("text/markdown; charset=utf-8", "md"),
    "pdf": ("application/pdf", "pdf"),
}


@dataclass(frozen=True)
class Exported:
    data: bytes
    media_type: str
    filename: str
    notices: list[str]


def list_sections() -> list[ProofSectionInfo]:
    return [ProofSectionInfo(id=s.id, title=s.title, order=s.order, wired=is_wired(s)) for s in ordered_specs()]  # type: ignore[arg-type]


def _digest(sections: list[SectionBase], version_id: UUID, region_codes: list[str]) -> str:
    payload = {"campaign_version_id": str(version_id), "regions": region_codes, "sections": [s.model_dump(mode="json") for s in sections]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _walk_claim_ids(node: Any, found: dict[str, None]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "claim_id" and isinstance(value, str):
                found[value] = None
            elif key == "claim_ids" and isinstance(value, list):
                found.update({str(v): None for v in value})
            else:
                _walk_claim_ids(value, found)
    elif isinstance(node, list):
        for value in node:
            _walk_claim_ids(value, found)


def references(sections: list[SectionBase]) -> tuple[list[UUID], list[UUID]]:
    """Claims and conflicts a report shows, taken from the typed sections (never guessed)."""
    claims: dict[str, None] = {}
    conflicts: dict[str, None] = {}
    for section in sections:
        content = getattr(section, "content", None)
        if content is None:
            continue
        dump = content.model_dump(mode="json")
        _walk_claim_ids(dump, claims)
        if section.id == "region_claims":
            for region in dump["regions"]:
                claims.update({c["id"]: None for cat in region["categories"] for c in cat["claims"]})
        if section.id == "conflicts":
            conflicts.update({c["id"]: None for c in dump["open"] + dump["resolved"]})
    return [UUID(c) for c in claims], [UUID(c) for c in conflicts]


def to_summary(row: m.ProofReport) -> ProofReportSummary:
    return ProofReportSummary(
        id=row.id, project_id=row.project_id, campaign_id=row.campaign_id, workspace_id=row.workspace_id,
        campaign_version_id=row.campaign_version_id, version_number=row.version_number, title=row.title,
        status=row.status, mode=row.mode, content_sha256=row.content_sha256, created_at=row.created_at,  # type: ignore[arg-type]
    )


async def create_report(user_id: UUID, campaign_id: UUID, body: ProofReportCreate) -> ProofReport:
    ctx = await build_context(user_id, campaign_id, body.region_codes)
    sections = await assemble(ctx)
    codes = [r.code for r in ctx.regions]
    missing = [MissingSection(id=s.id, title=s.title, reason=s.missing_reason or "") for s in sections if s.status == "missing"]  # type: ignore[arg-type]
    claim_ids, conflict_ids = references(sections)
    report_id = uuid4()
    async with session() as s, s.begin():
        number = 1 + (await s.scalar(select(func.max(m.ProofReport.version_number)).where(m.ProofReport.campaign_id == ctx.campaign.id)) or 0)
        report = ProofReport(
            id=report_id, project_id=ctx.project.id, campaign_id=ctx.campaign.id, workspace_id=ctx.workspace_id,
            campaign_version_id=ctx.version.id, version_number=number,
            title=body.title or f"Proof Report: {ctx.campaign.name}"[:200],
            status="partial" if missing else "complete", mode=ctx.mode,  # type: ignore[arg-type]
            content_sha256=_digest(sections, ctx.version.id, codes), created_at=ctx.now,
            schema_version="proof-report-v2", generated_by=user_id, target_region_codes=codes,
            sections=sections,  # type: ignore[arg-type]
            missing_sections=missing, referenced_claim_ids=claim_ids, referenced_conflict_ids=conflict_ids,
            kind_legend=KIND_LEGEND, legal_notice=LEGAL_NOTICE,
            assembly=AssemblyInfo(method="deterministic", model_called=False, registry_version=REGISTRY_VERSION,
                                  section_ids=[x.id for x in sections]),
        )
        s.add(m.ProofReport(
            id=report.id, project_id=report.project_id, campaign_id=report.campaign_id, workspace_id=report.workspace_id,
            campaign_version_id=report.campaign_version_id, version_number=number, title=report.title,
            status=report.status, mode=report.mode, content_sha256=report.content_sha256,
            content=report.model_dump(mode="json"), created_by=user_id, created_at=report.created_at,
        ))
        project = await s.get(m.Project, ctx.project.id)
        if project is not None:
            touch(project)
        await record_audit(
            s, action="proof_report.create", target_type="proof_report", target_id=str(report.id),
            workspace_id=ctx.workspace_id, actor_user_id=user_id,
            detail={"campaign_id": str(ctx.campaign.id), "version_number": number, "status": report.status},
        )
        try:
            await s.flush()
        except IntegrityError:
            raise Conflict("Another report for this campaign was created at the same time. Try again.") from None
    return report


async def list_reports(user_id: UUID, campaign_id: UUID, limit: int, offset: int) -> ProofReportPage:
    async with read_session() as s:
        campaign, _ = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        stmt = select(m.ProofReport).options(defer(m.ProofReport.content)).where(m.ProofReport.campaign_id == campaign.id)
        rows, total = await paginate(s, stmt.order_by(m.ProofReport.version_number.desc()), limit, offset)
    return ProofReportPage(items=[to_summary(r) for r in rows], limit=limit, offset=offset, total=total)


async def get_report(user_id: UUID, report_id: UUID) -> ProofReport:
    async with read_session() as s:
        row, _ = await get_owned(s, m.ProofReport, report_id, user_id, "Proof report")
    return ProofReport.model_validate(row.content)


def _filename(report: ProofReport, extension: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", report.title.lower()).strip("-")[:60] or "report"
    return f"omnicult-{slug}-v{report.version_number}.{extension}"


def _render(report: ProofReport, fmt: str) -> Exported:
    media_type, extension = FORMATS[fmt]
    notices: list[str] = []
    if fmt == "json":
        data = json.dumps(report.model_dump(mode="json"), indent=2).encode()
    elif fmt == "markdown":
        data = to_markdown(report_blocks(report)).encode()
    else:
        data, notices = to_pdf(report, report_blocks(report))
    return Exported(data, media_type, _filename(report, extension), notices)


async def export_inline(user_id: UUID, report_id: UUID, fmt: str) -> Exported:
    report = await get_report(user_id, report_id)
    return await asyncio.to_thread(_render, report, fmt)  # PDF layout is CPU work; keep the event loop free


async def create_export(user_id: UUID, report_id: UUID, fmt: str) -> ProofExport:
    async with read_session() as s:
        row, project = await get_owned(s, m.ProofReport, report_id, user_id, "Proof report")
    report = ProofReport.model_validate(row.content)
    exported = await asyncio.to_thread(_render, report, fmt)
    settings = get_settings()
    export_id = uuid4()
    key = f"proof/{project.id}/{report_id}/{export_id}.{FORMATS[fmt][1]}"
    in_database = settings.asset_storage_backend == "database"
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(seconds=settings.proof_export_url_ttl_seconds)
    digest = hashlib.sha256(exported.data).hexdigest()
    if not in_database:
        await blobs.store(key, exported.data, exported.media_type)
    try:
        async with session() as s, s.begin():
            s.add(m.ProofReportExport(
                id=export_id, report_id=report_id, project_id=project.id, format=fmt, filename=exported.filename,
                content_type=exported.media_type, byte_size=len(exported.data), sha256=digest, storage_key=key,
                data=exported.data if in_database else None, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                expires_at=expires, created_by=user_id, created_at=utcnow(),
            ))
            await record_audit(
                s, action="proof_report.export", target_type="proof_report", target_id=str(report_id),
                workspace_id=project.workspace_id, actor_user_id=user_id, detail={"format": fmt, "export_id": str(export_id)},
            )
    except Exception:
        if not in_database:
            await blobs.discard([key])
        raise
    return ProofExport(
        id=export_id, report_id=report_id, format=fmt,  # type: ignore[arg-type]
        filename=exported.filename, content_type=exported.media_type, byte_size=len(exported.data), sha256=digest,
        download_url=f"{API}/proof-exports/{export_id}/download?token={token}", expires_at=expires, notices=exported.notices,
    )


async def download_export(export_id: UUID, token: str) -> Response:
    """The stored export for a valid, unexpired link. Every failure is the same 404, so a link reveals nothing."""
    async with read_session() as s:
        row = await s.get(m.ProofReportExport, export_id)
    expected = row.token_hash if row is not None else hashlib.sha256(b"").hexdigest()
    valid = hmac.compare_digest(expected, hashlib.sha256(token.encode()).hexdigest())
    if row is None or not valid or row.expires_at <= utcnow():
        raise NotFound("The export was not found, or its link has expired.")
    data = row.data
    if data is None:  # blobs.read looks the bytes up by key; this stand-in has the three fields it reads
        data = await blobs.read(cast(Any, SimpleNamespace(id=row.id, project_id=row.project_id, storage_name=row.storage_key)))
    return Response(
        data, media_type=row.content_type,
        headers=blobs.CONTENT_HEADERS | {"Content-Disposition": f'attachment; filename="{row.filename}"'},
    )
