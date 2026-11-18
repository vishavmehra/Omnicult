"""The media pipeline: probe an asset, extract keyframes, the audio track and thumbnails with ffmpeg, and store every
derived file through the blob store (store, attach, discard) as an `assets` row linked to its parent.

`MediaPipeline` is what the Creative X-Ray workflow calls (`deps.media`). Both calls are idempotent: an asset whose
processing is `ready` reuses its stored derived files, so a re-run of X-Ray does not extract twice. Work on one asset is
serialised in this process (the run engine is single-instance, D-022). The ffmpeg work happens in a temporary directory
that is removed afterwards; nothing else is written to disk.
"""

import asyncio
import hashlib
import logging
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from PIL import Image
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import NotFound, ValidationFailed
from app.db import blobs
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.media import ffmpeg
from app.media.keyframes import select_keyframe_times
from app.media.sniff import EXTENSIONS
from app.media import textrender
from app.media.textrender import RenderResult, load_image
from app.media.types import PreparedAudio, PreparedFrame, PreparedMedia
from app.schemas.common import ErrorDetail
from app.schemas.media import MediaCapabilities, MediaLimits, RenderTextRequest, ToolStatus
from app.schemas.xray import MediaProbe

log = logging.getLogger("omnicult.media")
THUMBNAIL_PX = 320
PROCESSING_FAILED = "The media could not be processed."
_locks: dict[UUID, asyncio.Lock] = {}


def _lock(asset_id: UUID) -> asyncio.Lock:
    # ponytail: one small Lock per processed asset kept for the process lifetime; prune if processing volume grows
    return _locks.setdefault(asset_id, asyncio.Lock())


def probe_summary(kind: str, content_type: str, result: ffmpeg.ProbeResult) -> MediaProbe:
    return MediaProbe(
        kind=kind,  # type: ignore[arg-type]
        container=result.container, duration_ms=result.duration_ms, width=result.width, height=result.height, fps=result.fps,
        has_video=result.has_video, has_audio=result.has_audio, video_codec=result.video_codec, audio_codec=result.audio_codec,
    )


def check_limits(kind: str, result: ffmpeg.ProbeResult) -> None:
    """Upload rules from the probe: the right streams, and a known duration within MAX_MEDIA_SECONDS."""
    limit = get_settings().max_media_seconds

    def refuse(message: str) -> ValidationFailed:
        return ValidationFailed(message, details=[ErrorDetail(field="file", message=message)])

    if kind == "video" and not result.has_video:
        raise refuse("The file has no video stream.")
    if kind == "audio" and (not result.has_audio or result.has_video):
        raise refuse("The file is not audio only: it has no audio stream, or it also has video.")
    if not result.duration_ms:
        raise refuse("The length of the file could not be determined, or it is empty.")
    if result.duration_ms > limit * 1000:
        raise refuse(f"The file is {result.duration_ms / 1000:.0f} seconds long; the limit is {limit:.0f} seconds.")


async def probe_bytes(data: bytes, content_type: str) -> ffmpeg.ProbeResult:
    """ffprobe over uploaded bytes (written to a temporary file that is removed straight away)."""
    with tempfile.TemporaryDirectory(prefix="omnicult-probe-") as tmp:
        path = Path(tmp) / f"input.{EXTENSIONS.get(content_type, 'bin')}"
        await asyncio.to_thread(path.write_bytes, data)
        return await ffmpeg.probe_file(path)


def thumbnail_jpeg(frame: bytes) -> tuple[bytes, int, int]:
    image = Image.open(BytesIO(frame))
    image.load()
    image = image.convert("RGB")
    image.thumbnail((THUMBNAIL_PX, THUMBNAIL_PX))
    out = BytesIO()
    image.save(out, format="JPEG", quality=80)
    return out.getvalue(), image.width, image.height


@dataclass
class _Derived:
    role: str
    data: bytes
    content_type: str
    at_ms: int | None = None
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    id: UUID | None = None


class MediaPipeline:
    """One per run. Caches the original bytes so probe and extract read them from storage once."""

    def __init__(self) -> None:
        self._bytes: dict[UUID, bytes] = {}

    async def _row(self, asset_id: UUID) -> m.Asset:
        async with read_session() as s:
            row = await s.get(m.Asset, asset_id)
        if row is None:
            raise NotFound("Asset was not found.")
        return row

    async def _load(self, row: m.Asset) -> bytes:
        if row.id not in self._bytes:
            try:
                self._bytes[row.id] = await blobs.read(row)
            except NotFound:
                await self._set_status(row.id, None, PROCESSING_FAILED, upload_status="failed")
                raise
        return self._bytes[row.id]

    async def probe(self, asset_id: UUID) -> MediaProbe:
        row = await self._row(asset_id)
        data = await self._load(row)
        if row.kind == "image":
            image = await asyncio.to_thread(load_image, data)
            return MediaProbe(
                kind="image", container=row.content_type, duration_ms=None, width=image.width, height=image.height, fps=None,
                has_video=False, has_audio=False, video_codec=None, audio_codec=None,
            )
        result = await probe_bytes(data, row.content_type)
        check_limits(row.kind, result)
        return probe_summary(row.kind, row.content_type, result)

    async def extract(self, asset_id: UUID) -> PreparedMedia:
        async with _lock(asset_id):
            row = await self._row(asset_id)
            if row.processing_status == "ready":
                reused = await self._reuse(row)
                if reused is not None:
                    return reused
            await self._set_status(asset_id, "processing", None)
            try:
                return await self._extract_new(row)
            except BaseException as exc:
                message = str(exc) if isinstance(exc, (ffmpeg.MediaProcessingFailed, ffmpeg.MediaToolMissing, ValidationFailed)) else PROCESSING_FAILED
                try:
                    await self._set_status(asset_id, "failed", message[:300])
                except Exception:  # the original failure matters more than the status write
                    log.warning("could not record media processing failure", extra={"asset_id": str(asset_id)})
                raise

    # --- internals -------------------------------------------------------------------------

    async def _set_status(self, asset_id: UUID, status: str | None, error: str | None, *, upload_status: str | None = None) -> None:
        async with session() as s, s.begin():
            row = await s.get(m.Asset, asset_id)
            if row is None:
                return
            if status is not None:
                row.processing_status = status
            row.processing_error = error
            if upload_status is not None:
                row.upload_status = upload_status

    async def _reuse(self, row: m.Asset) -> PreparedMedia | None:
        async with read_session() as s:
            derived = (await s.execute(
                select(m.Asset).where(m.Asset.parent_asset_id == row.id).order_by(m.Asset.derived_at_ms, m.Asset.created_at)
            )).scalars().all()
        keyframes = [d for d in derived if d.derived_role == "keyframe"]
        audio = next((d for d in derived if d.derived_role == "audio_track"), None)
        thumb = next((d for d in derived if d.derived_role == "thumbnail"), None)
        info = row.media_info or {}
        stored_probe = info.get("probe")
        if stored_probe is None or (row.kind == "video" and not keyframes) or (row.kind == "audio" and audio is None):
            return None
        frames = [
            PreparedFrame(f"f{i}", d.derived_at_ms or 0, d.id, d.content_type, await blobs.read(d))
            for i, d in enumerate(keyframes, 1)
        ]
        if row.kind == "image":
            frames = [PreparedFrame("f1", 0, None, row.content_type, await self._load(row))]
        prepared_audio = PreparedAudio(audio.id, audio.content_type, await blobs.read(audio), audio.duration_ms) if audio else None
        return self._prepared(MediaProbe.model_validate(stored_probe), frames, prepared_audio, thumb.id if thumb else None, info)

    @staticmethod
    def _prepared(probe: MediaProbe, frames: list[PreparedFrame], audio: PreparedAudio | None, thumb: UUID | None, info: dict) -> PreparedMedia:
        sidecar = info.get("sidecar") or {}
        return PreparedMedia(
            probe=probe, frames=frames, audio=audio, thumbnail_asset_id=thumb,
            sidecar_segments=list(sidecar.get("segments") or []),
            sidecar_notes=sidecar.get("text") if sidecar.get("format") == "text" else None,
            container_tags=dict(info.get("tags") or {}),
        )

    async def _extract_new(self, row: m.Asset) -> PreparedMedia:
        settings = get_settings()
        data = await self._load(row)
        items: list[_Derived] = []
        if row.kind == "image":
            image = await asyncio.to_thread(load_image, data)
            probe = MediaProbe(
                kind="image", container=row.content_type, duration_ms=None, width=image.width, height=image.height, fps=None,
                has_video=False, has_audio=False, video_codec=None, audio_codec=None,
            )
            jpeg, w, h = await asyncio.to_thread(thumbnail_jpeg, data)
            items.append(_Derived("thumbnail", jpeg, "image/jpeg", width=w, height=h))
            frame_data: list[tuple[int, bytes]] = []
            audio_data: bytes | None = None
        else:
            with tempfile.TemporaryDirectory(prefix="omnicult-media-") as tmp:
                work = Path(tmp)
                src = work / f"input.{EXTENSIONS.get(row.content_type, 'bin')}"
                await asyncio.to_thread(src.write_bytes, data)
                result = await ffmpeg.probe_file(src)
                check_limits(row.kind, result)
                probe = probe_summary(row.kind, row.content_type, result)
                frame_data, audio_data = [], None
                if row.kind == "video":
                    scenes = await ffmpeg.detect_scene_changes(src, settings.keyframe_scene_threshold)
                    times = select_keyframe_times(
                        scenes, result.duration_ms or 0, min_gap_ms=settings.keyframe_min_gap_ms,
                        max_gap_ms=settings.keyframe_max_gap_ms, max_count=settings.keyframe_max_count,
                    )
                    for at in times:
                        try:
                            frame_data.append((at, await ffmpeg.extract_frame(src, at, work / f"f{at}.jpg", max_width=settings.keyframe_max_width)))
                        except ffmpeg.MediaProcessingFailed:  # one undecodable moment does not lose the video
                            log.warning("keyframe skipped", extra={"asset_id": str(row.id), "at_ms": at})
                    if not frame_data:
                        raise ffmpeg.MediaProcessingFailed("No frame could be extracted from the video.")
                if result.has_audio:
                    audio_data = await ffmpeg.extract_audio(src, work / "audio.wav", max_seconds=settings.max_media_seconds)
            for at, jpeg in frame_data:
                width, height = await asyncio.to_thread(lambda b=jpeg: Image.open(BytesIO(b)).size)
                items.append(_Derived("keyframe", jpeg, "image/jpeg", at_ms=at, width=width, height=height))
            if frame_data:
                middle = frame_data[len(frame_data) // 2][1]
                jpeg, w, h = await asyncio.to_thread(thumbnail_jpeg, middle)
                items.append(_Derived("thumbnail", jpeg, "image/jpeg", width=w, height=h))
            if audio_data:
                items.append(_Derived("audio_track", audio_data, "audio/wav", duration_ms=probe.duration_ms))
        await self._store(row, probe, items)
        frames = [PreparedFrame(f"f{i}", d.at_ms or 0, d.id, d.content_type, d.data) for i, d in enumerate((x for x in items if x.role == "keyframe"), 1)]
        if row.kind == "image":
            frames = [PreparedFrame("f1", 0, None, row.content_type, data)]
        audio_item = next((x for x in items if x.role == "audio_track"), None)
        audio = PreparedAudio(audio_item.id, "audio/wav", audio_item.data, audio_item.duration_ms) if audio_item and audio_item.id else None
        thumb = next((x.id for x in items if x.role == "thumbnail"), None)
        return self._prepared(probe, frames, audio, thumb, row.media_info or {})

    async def _store(self, parent: m.Asset, probe: MediaProbe, items: list[_Derived]) -> None:
        """Store the derived files (blob store protocol: store first, rows and attach in one transaction, discard on
        failure) and mark the parent `ready` in that same transaction."""
        prefix = parent.storage_name.rsplit("/", 1)[0] if "/" in parent.storage_name else ""
        keys: list[str] = []
        try:
            for item in items:
                item.id = uuid4()
                key = f"{prefix}/{item.id}" if prefix else str(item.id)
                await blobs.store(key, item.data, item.content_type)
                keys.append(key)
            now = utcnow()
            async with session() as s, s.begin():
                for item, key in zip(items, keys):
                    stamp = f"{item.at_ms:06d}ms" if item.at_ms is not None else "main"
                    row = m.Asset(
                        id=item.id, project_id=parent.project_id, kind="audio" if item.role == "audio_track" else "image",
                        filename=f"{item.role}-{stamp}.{EXTENSIONS.get(item.content_type, 'wav')}", content_type=item.content_type,
                        size_bytes=len(item.data), sha256=hashlib.sha256(item.data).hexdigest(), storage_name=key, created_at=now,
                        rights_confirmed=parent.rights_confirmed, rights_confirmed_at=parent.rights_confirmed_at,
                        duration_ms=item.duration_ms, width=item.width, height=item.height, parent_asset_id=parent.id,
                        derived_role=item.role, derived_at_ms=item.at_ms,
                    )
                    s.add(row)
                    blobs.attach(s, row, item.data)
                live = await s.get(m.Asset, parent.id)
                assert live is not None
                live.processing_status, live.processing_error = "ready", None
                live.duration_ms, live.width, live.height = probe.duration_ms, probe.width, probe.height
                live.media_info = {**(live.media_info or {}), "probe": probe.model_dump(mode="json")}
        except BaseException:
            await blobs.discard(keys)
            raise


# --- reads and previews used by the API -------------------------------------------------------------------


async def capabilities() -> MediaCapabilities:
    tools = await asyncio.to_thread(ffmpeg.detect_tools)
    settings = get_settings()

    def status(tool: ffmpeg.Tool) -> ToolStatus:
        return ToolStatus(available=tool.available, version=tool.version, message=tool.message)

    return MediaCapabilities(
        ffmpeg=status(tools.ffmpeg), ffprobe=status(tools.ffprobe), text_shaping=textrender.shaping_engine(),
        scripts=textrender.available_scripts(),  # type: ignore[arg-type]
        limits=MediaLimits(
            max_image_bytes=settings.max_image_bytes, max_media_bytes=settings.max_media_bytes,
            max_media_seconds=settings.max_media_seconds,
        ),
    )


async def render_text_preview(user_id: UUID, project_id: UUID, body: RenderTextRequest) -> tuple[bytes, RenderResult]:
    """Render regional text onto an image in code and restore locked regions from the original (PNG bytes + placements).
    Read access to the project is enough: nothing is stored."""
    from app.services.common import conflict, get_owned, get_project

    async def load(asset_id: UUID | None, field: str):  # type: ignore[no-untyped-def]
        if asset_id is None:
            return None
        async with read_session() as s:
            row, _ = await get_owned(s, m.Asset, asset_id, user_id, "Asset", field)
        if row.project_id != project_id:
            raise conflict(field, "The asset belongs to another project.")
        if row.kind != "image":
            raise conflict(field, "Only image assets can be used here.")
        return await asyncio.to_thread(textrender.load_image, await blobs.read(row))

    async with read_session() as s:
        await get_project(s, user_id, project_id)
    original = await load(body.original_asset_id, "original_asset_id")
    base = await load(body.base_asset_id, "base_asset_id")
    canvas = (body.width, body.height) if body.width and body.height else None
    result = await asyncio.to_thread(
        textrender.render_text, body.boxes, base=base, original=original, locked=body.locked_regions, canvas=canvas,
        background=body.background,
    )
    return await asyncio.to_thread(textrender.encode_png, result.image), result
