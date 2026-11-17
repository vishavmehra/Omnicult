"""Asset bytes behind ASSET_STORAGE_BACKEND: `database` (a table; tests), `local` (files under storage/assets;
development), `gcs` (a private Cloud Storage bucket, called only by this server with its service account's ADC), or
`supabase` (legacy: a private Supabase Storage bucket over its REST API with SUPABASE_SECRET_KEY).

Upload flow: `await store(key, data, content_type)` before the asset row's transaction, `attach(s, row, data)` inside
it, and `await discard([key])` if that transaction fails. With `database`, the bytes commit atomically with the row.
Keys are `{owner_id}/{asset_id}` (object_key): server-generated, never a user-supplied filename. The browser never
talks to Storage; every read goes through the API's ownership check first.
"""

import asyncio
import itertools
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi.responses import Response
from google.api_core import exceptions as gexc
from requests.exceptions import Timeout as RequestsTimeout
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFound, ProviderFailed, ProviderTimeout
from app.db import models as m
from app.db.session import read_session

BUCKET = "assets"  # private; created by migration 0006
CONTENT_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}
TIMEOUT = httpx.Timeout(30.0, connect=5.0)
BACKOFF = (0.25, 0.75)  # one retry per entry, for 5xx and network errors only
UNAVAILABLE = "Asset storage is unavailable right now. Try again shortly."
log = logging.getLogger("nativeproof.storage")
_transport: httpx.AsyncBaseTransport | None = None  # tests install an httpx.MockTransport
_gcs: Any = None  # a google.cloud.storage.Client, created on first use; tests install a fake
LOCAL_ROOT = Path("storage/assets")  # ASSET_STORAGE_BACKEND=local (relative to the working directory; git-ignored)
GCS_TIMEOUT = 30.0  # seconds per Cloud Storage call; the client library retries transient errors within it


def object_key(owner_id: UUID, asset_id: UUID) -> str:
    return f"{owner_id}/{asset_id}"


def _supabase() -> bool:
    return get_settings().asset_storage_backend == "supabase"


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


async def _call(method: str, path: str, operation: str, **kwargs: Any) -> httpx.Response:
    """One Storage request with bounded retries. Provider bodies are never logged or shown; only status codes."""
    settings = get_settings()
    assert settings.supabase_url and settings.supabase_secret_key  # enforced at startup (config)
    key = settings.supabase_secret_key.get_secret_value()
    headers = {"apikey": key, "Authorization": f"Bearer {key}", **kwargs.pop("headers", {})}
    url = f"{settings.supabase_url.rstrip('/')}/storage/v1/{path}"
    failure, timed_out = "", False
    # a client per call (uploads are rare); share one from the lifespan if storage traffic grows
    async with httpx.AsyncClient(timeout=TIMEOUT, transport=_transport) as client:
        for delay in (*BACKOFF, None):
            try:
                response = await client.request(method, url, headers=headers, **kwargs)
            except httpx.TransportError as exc:  # connect/read errors and timeouts
                failure, timed_out = type(exc).__name__, isinstance(exc, httpx.TimeoutException)
            else:
                if response.status_code < 500:
                    return response
                failure, timed_out = f"status {response.status_code}", False
            if delay is not None:
                await asyncio.sleep(delay)
    log.warning("asset storage unavailable", extra={"operation": operation, "failure": failure})
    raise (ProviderTimeout if timed_out else ProviderFailed)(UNAVAILABLE)


def _missing(response: httpx.Response) -> bool:
    if response.status_code == 404:
        return True
    try:  # some Storage versions answer a missing object with 400 and {"statusCode": "404"}
        return response.status_code == 400 and str(response.json().get("statusCode")) == "404"
    except ValueError:
        return False


def _refused(response: httpx.Response, operation: str) -> ProviderFailed:
    log.warning("asset storage refused the request", extra={"operation": operation, "status": response.status_code})
    return ProviderFailed(UNAVAILABLE)


async def store(key: str, data: bytes, content_type: str) -> None:
    backend = get_settings().asset_storage_backend
    if backend == "gcs":  # if_generation_match=0: create only, never overwrite (supabase: x-upsert false)
        await _gcs_call("upload", key, "upload_from_string", data, content_type=content_type, if_generation_match=0)
    elif backend == "local":
        path = _local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)
    elif backend == "supabase":
        response = await _call("POST", f"object/{BUCKET}/{key}", "upload", content=data,
                               headers={"Content-Type": content_type, "x-upsert": "false"})
        if not response.is_success:
            raise _refused(response, "upload")


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
        return
    if not (_supabase() and keys):
        return
    for chunk in itertools.batched(keys, 1000):
        try:
            response = await _call("DELETE", f"object/{BUCKET}", "delete", json={"prefixes": list(chunk)})
            if not response.is_success:
                raise _refused(response, "delete")
        except Exception as exc:  # the caller is already handling a failure; an orphaned object is the lesser harm
            log.warning("stored objects left orphaned", extra={"count": len(chunk), "failure": type(exc).__name__})


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
    if _supabase():
        response = await _call("GET", f"object/{BUCKET}/{row.storage_name}", "download")
        if response.is_success:
            return response.content
        if not _missing(response):
            raise _refused(response, "download")
    raise NotFound("Asset file was not found.")


async def content_response(row: m.Asset) -> Response:
    data = await read(row)
    disposition = f"inline; filename*=utf-8''{quote(row.filename)}"
    return Response(data, media_type=row.content_type, headers=CONTENT_HEADERS | {"Content-Disposition": disposition})
