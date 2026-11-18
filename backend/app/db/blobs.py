"""Asset bytes behind ASSET_STORAGE_BACKEND: `database` (a table; tests), `local` (files under storage/assets;
development), or `gcs` (a private Cloud Storage bucket, called only by this server with its service account's ADC).

Upload flow: `await store(key, data, content_type)` before the asset row's transaction, `attach(s, row, data)` inside
it, and `await discard([key])` if that transaction fails. With `database`, the bytes commit atomically with the row.
Keys are `{owner_id}/{asset_id}` (object_key): server-generated, never a user-supplied filename. The browser never
talks to Storage; every read goes through the API's ownership check first.
"""

import asyncio
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

from fastapi.responses import Response
from google.api_core import exceptions as gexc
from requests.exceptions import Timeout as RequestsTimeout
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFound, ProviderFailed, ProviderTimeout
from app.db import models as m
from app.db.session import read_session

CONTENT_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}
UNAVAILABLE = "Asset storage is unavailable right now. Try again shortly."
log = logging.getLogger("omnicult.storage")
_gcs: Any = None  # a google.cloud.storage.Client, created on first use; tests install a fake
LOCAL_ROOT = Path("storage/assets")  # ASSET_STORAGE_BACKEND=local (relative to the working directory; git-ignored)
GCS_TIMEOUT = 30.0  # seconds per Cloud Storage call; the client library retries transient errors within it


def object_key(owner_id: UUID, asset_id: UUID) -> str:
    return f"{owner_id}/{asset_id}"


def _external() -> bool:
    """True when the bytes live outside the database (a row may still hold them if it predates a backend switch)."""
    return get_settings().asset_storage_backend != "database"


async def _gcs_call(operation: str, key: str, method: str, *args: Any, **kwargs: Any) -> Any:
    """One blocking Cloud Storage call on a worker thread. NotFound passes through; every other failure is mapped to a
    provider error with a fixed message (the library's own text is never logged or shown, only the exception type)."""
    global _gcs
    try:
        if _gcs is None:
            from google.cloud import storage  # imported here: only the gcs backend needs the library and credentials

            _gcs = await asyncio.to_thread(storage.Client)
        blob = _gcs.bucket(get_settings().gcs_bucket).blob(key)
        return await asyncio.to_thread(getattr(blob, method), *args, timeout=GCS_TIMEOUT, **kwargs)
    except gexc.NotFound:
        raise
    except Exception as exc:
        log.warning("asset storage unavailable", extra={"operation": operation, "failure": type(exc).__name__})
        timed_out = isinstance(exc, (TimeoutError, gexc.DeadlineExceeded, RequestsTimeout))
        raise (ProviderTimeout if timed_out else ProviderFailed)(UNAVAILABLE) from None


def _local_path(key: str) -> Path:
    path = (LOCAL_ROOT / key).resolve()
    if not path.is_relative_to(LOCAL_ROOT.resolve()):  # keys are server-generated; this is a backstop
        raise NotFound("Asset file was not found.")
    return path


async def store(key: str, data: bytes, content_type: str) -> None:
    backend = get_settings().asset_storage_backend
    if backend == "gcs":  # if_generation_match=0: create only, never overwrite
        await _gcs_call("upload", key, "upload_from_string", data, content_type=content_type, if_generation_match=0)
    elif backend == "local":
        path = _local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)


def attach(s: AsyncSession, row: m.Asset, data: bytes) -> None:
    if not _external():
        s.add(m.AssetBlob(asset_id=row.id, project_id=row.project_id, data=data))


async def discard(keys: list[str]) -> None:
    """Best effort: delete stored objects whose rows will not exist (a failed upload transaction). Never raises."""
    backend = get_settings().asset_storage_backend
    if backend in ("gcs", "local"):
        for key in keys:
            try:
                if backend == "gcs":
                    await _gcs_call("delete", key, "delete")
                else:
                    await asyncio.to_thread(_local_path(key).unlink, missing_ok=True)
            except Exception as exc:  # an orphaned object is the lesser harm
                log.warning("stored objects left orphaned", extra={"count": 1, "failure": type(exc).__name__})


async def read(row: m.Asset) -> bytes:
    """The asset's bytes from whichever backend holds them (a row may predate a backend switch)."""
    async with read_session() as s:
        data = await s.scalar(select(m.AssetBlob.data).where(m.AssetBlob.asset_id == row.id,
                                                             m.AssetBlob.project_id == row.project_id))
    if data is not None:
        return data
    backend = get_settings().asset_storage_backend
    if backend == "gcs":
        try:
            return await _gcs_call("download", row.storage_name, "download_as_bytes")
        except gexc.NotFound:
            raise NotFound("Asset file was not found.") from None
    if backend == "local":
        try:
            return await asyncio.to_thread(_local_path(row.storage_name).read_bytes)
        except FileNotFoundError:
            raise NotFound("Asset file was not found.") from None
    raise NotFound("Asset file was not found.")


async def content_response(row: m.Asset) -> Response:
    data = await read(row)
    disposition = f"inline; filename*=utf-8''{quote(row.filename)}"
    return Response(data, media_type=row.content_type, headers=CONTENT_HEADERS | {"Content-Disposition": disposition})


async def signed_url(row: m.Asset, ttl_seconds: int) -> str | None:
    """A V4 signed GET URL (media stream), after the caller's ownership check, for an object in Cloud Storage.

    None for every other backend, for bytes that live in the database, and whenever signing is not possible (the
    caller then streams through the API instead). Cloud Run credentials hold no private key, so signing goes through the
    IAM Credentials API using the runtime service account (it needs roles/iam.serviceAccountTokenCreator on itself)."""
    if get_settings().asset_storage_backend != "gcs":
        return None
    async with read_session() as s:
        if await s.scalar(select(m.AssetBlob.asset_id).where(m.AssetBlob.asset_id == row.id)) is not None:
            return None

    def sign() -> str:
        global _gcs
        if _gcs is None:
            from google.cloud import storage

            _gcs = storage.Client()
        blob = _gcs.bucket(get_settings().gcs_bucket).blob(row.storage_name)
        extra: dict[str, Any] = {}
        credentials = getattr(_gcs, "_credentials", None)
        if credentials is not None and getattr(credentials, "service_account_email", None) and not hasattr(credentials, "signer"):
            from google.auth.transport.requests import Request

            credentials.refresh(Request())
            extra = {"service_account_email": credentials.service_account_email, "access_token": credentials.token}
        return blob.generate_signed_url(
            version="v4", expiration=timedelta(seconds=ttl_seconds), method="GET", response_type=row.content_type,
            response_disposition="inline", **extra,
        )

    try:
        return await asyncio.to_thread(sign)
    except Exception as exc:  # signing is an optimisation; the stream endpoint always works
        log.warning("signed url unavailable", extra={"failure": type(exc).__name__})
        return None
