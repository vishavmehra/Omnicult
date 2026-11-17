"""Uploaded assets (contracts/README §13, D-035): images, and short video and audio (media stream).

Uploads are typed by their magic bytes, not by filename or header, size-limited per kind, and stored under server-generated
keys `{owner_id}/{asset_id}` in the ASSET_STORAGE_BACKEND (app/db/blobs.py). Video and audio also need the uploader's
rights confirmation, an ffprobe check (known duration within MAX_MEDIA_SECONDS, the right streams), and any text sidecar
or container metadata is scanned and redacted of emails and phone numbers before a model can see it.
Derived files (keyframes, thumbnails, the audio track) are `assets` rows with `parent_asset_id` set; lists hide them.
"""

import hashlib
import unicodedata
from datetime import timedelta
from pathlib import Path, PureWindowsPath
from uuid import UUID, uuid4

from fastapi.responses import Response
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import ValidationFailed
from app.db import blobs
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.media import sidecar as sidecar_text
from app.media.sniff import ALLOWED, sniff
from app.schemas.assets import Asset, AssetKind, AssetPage, AssetStatus, AssetUrl, DerivedAsset, SidecarStatus
from app.schemas.common import ErrorDetail
from app.services import media as media_service
from app.services.common import get_owned, get_project, paginate, touch

API = "/api/v1"


def safe_filename(name: str | None) -> str:
    """Display name only: no directories or control characters. Never used as a storage path."""
    base = PureWindowsPath(Path(name or "").name).name  # strips both / and \ directory parts
    cleaned = "".join(ch for ch in base if unicodedata.category(ch)[0] != "C").strip()
    return cleaned[:200] or "upload"


def content_path(asset_id: UUID) -> str:
    return f"{API}/assets/{asset_id}/content"


def to_asset(row: m.Asset) -> Asset:
    return Asset(
        id=row.id, project_id=row.project_id, kind=row.kind, filename=row.filename,  # type: ignore[arg-type]
        content_type=row.content_type, size_bytes=row.size_bytes, sha256=row.sha256, created_at=row.created_at,
        content_url=content_path(row.id), upload_status=row.upload_status,  # type: ignore[arg-type]
        processing_status=row.processing_status, processing_error=row.processing_error,  # type: ignore[arg-type]
        rights_confirmed=row.rights_confirmed, duration_ms=row.duration_ms, width=row.width, height=row.height,
        parent_asset_id=row.parent_asset_id, derived_role=row.derived_role,  # type: ignore[arg-type]
        derived_at_ms=row.derived_at_ms,
    )


def _invalid(message: str, field: str = "file") -> ValidationFailed:
    return ValidationFailed(message, details=[ErrorDetail(field=field, message=message)])


def max_bytes(kind: AssetKind = "image") -> int:
    settings = get_settings()
    return settings.max_image_bytes if kind == "image" else settings.max_media_bytes


async def upload_asset(
    user_id: UUID, project_id: UUID, kind: AssetKind, filename: str | None, data: bytes, *, rights_confirmed: bool = False,
    sidecar: bytes | None = None,
) -> Asset:
    """`data` must already be bounded by the caller to max_bytes(kind) + 1; `sidecar` to MAX_SIDECAR_BYTES + 1."""
    async with session() as s:
        await get_project(s, user_id, project_id, writable=True)
    limit = max_bytes(kind)
    if not data:
        raise _invalid("The file is empty.")
    if len(data) > limit:
        raise _invalid(f"The file is larger than the {limit // (1024 * 1024)} MB limit for {kind} uploads.")
    detected = sniff(data, kind)
    if detected is None:
        raise _invalid(f"The file content is not a supported {kind} format ({ALLOWED[kind]}).")
    content_type, _ = detected
    media_fields: dict = {}
    if kind == "image":
        if sidecar is not None:
            raise _invalid("A text sidecar goes with video or audio, not images.", "sidecar")
    else:
        if not rights_confirmed:
            raise _invalid(
                f"Confirm that you hold the rights to use this {kind} before uploading it (rights_confirmed).", "rights_confirmed"
            )
        probe = await media_service.probe_bytes(data, content_type)  # MediaToolMissing (503) when ffprobe is absent
        media_service.check_limits(kind, probe)
        tags, tag_redactions, dropped = sidecar_text.clean_tags(probe.tags)
        info: dict = {"container": probe.container, "tags": tags, "tags_redacted": tag_redactions, "tags_dropped": dropped}
        if sidecar is not None:
            try:
                info["sidecar"] = _sidecar_record(sidecar_text.parse_sidecar(sidecar))
            except sidecar_text.SidecarError as exc:
                raise _invalid(str(exc), "sidecar") from None
        media_fields = {
            "duration_ms": probe.duration_ms, "width": probe.width, "height": probe.height, "media_info": info,
            "processing_status": "pending",
        }
    now = utcnow()
    asset_id = uuid4()
    storage_name = blobs.object_key(user_id, asset_id)
    await blobs.store(storage_name, data, content_type)  # database: committed with the row below
    try:
        async with session() as s, s.begin():
            project = await get_project(s, user_id, project_id, writable=True)
            row = m.Asset(
                id=asset_id, project_id=project_id, kind=kind, filename=safe_filename(filename), content_type=content_type,
                size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), storage_name=storage_name, created_at=now,
                rights_confirmed=rights_confirmed, rights_confirmed_at=now if rights_confirmed else None, **media_fields,
            )
            s.add(row)
            blobs.attach(s, row, data)
            touch(project)
    except BaseException:
        await blobs.discard([storage_name])
        raise
    return to_asset(row)


def _sidecar_record(parsed: sidecar_text.Sidecar) -> dict:
    return {"format": parsed.format, "text": parsed.text, "segments": parsed.segments, "redacted": parsed.redacted}


async def list_assets(
    user_id: UUID, project_id: UUID, limit: int, offset: int, kind: AssetKind | None, include_derived: bool = False
) -> AssetPage:
    async with read_session() as s:
        await get_project(s, user_id, project_id)
        stmt = select(m.Asset).where(m.Asset.project_id == project_id)
        if kind is not None:
            stmt = stmt.where(m.Asset.kind == kind)
        if not include_derived:
            stmt = stmt.where(m.Asset.parent_asset_id.is_(None))
        rows, total = await paginate(s, stmt.order_by(m.Asset.created_at.desc(), m.Asset.id), limit, offset)
    return AssetPage(items=[to_asset(row) for row in rows], limit=limit, offset=offset, total=total)


async def get_asset(user_id: UUID, asset_id: UUID) -> Asset:
    async with read_session() as s:
        row, _ = await get_owned(s, m.Asset, asset_id, user_id, "Asset")
    return to_asset(row)


async def asset_content(user_id: UUID, asset_id: UUID) -> Response:
    async with read_session() as s:
        row, _ = await get_owned(s, m.Asset, asset_id, user_id, "Asset")
    return await blobs.content_response(row)


async def asset_status(user_id: UUID, asset_id: UUID) -> AssetStatus:
    async with read_session() as s:
        row, _ = await get_owned(s, m.Asset, asset_id, user_id, "Asset")
        derived = (await s.execute(
            select(m.Asset).where(m.Asset.parent_asset_id == asset_id).order_by(m.Asset.derived_at_ms, m.Asset.created_at)
        )).scalars().all()
    info = row.media_info or {}
    car = info.get("sidecar") or {}
    return AssetStatus(
        asset_id=row.id, kind=row.kind,  # type: ignore[arg-type]
        upload_status=row.upload_status, processing_status=row.processing_status,  # type: ignore[arg-type]
        processing_error=row.processing_error, rights_confirmed=row.rights_confirmed, duration_ms=row.duration_ms,
        sidecar=SidecarStatus(present=bool(car), format=car.get("format"), redacted=dict(car.get("redacted") or {})),
        metadata_redacted=dict(info.get("tags_redacted") or {}),
        derived=[
            DerivedAsset(
                id=d.id, role=d.derived_role, derived_at_ms=d.derived_at_ms, content_type=d.content_type,  # type: ignore[arg-type]
                size_bytes=d.size_bytes, content_url=content_path(d.id),
            )
            for d in derived
        ],
    )


async def asset_url(user_id: UUID, asset_id: UUID) -> AssetUrl:
    """A short-lived signed URL when the bytes are in Cloud Storage (and signing works), else the authenticated stream."""
    async with read_session() as s:
        row, _ = await get_owned(s, m.Asset, asset_id, user_id, "Asset")
    ttl = get_settings().media_signed_url_seconds
    signed = await blobs.signed_url(row, ttl)
    if signed is None:
        return AssetUrl(asset_id=row.id, kind="stream", url=content_path(row.id), expires_at=None)
    return AssetUrl(asset_id=row.id, kind="signed", url=signed, expires_at=utcnow() + timedelta(seconds=ttl))

