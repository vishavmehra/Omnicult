"""Run engine: validates and records runs, then executes workflows as in-process tasks (D-022).

Execution is not durable. On startup every queued or running run becomes failed with
RUN_INTERRUPTED. A semaphore bounds concurrent workflows, and a lock keeps the per-user
active-run limit exact. Both are process-wide, which is correct only for a single instance.

Workflows (app.workflows, owned by the AI workstream) are pure: this module loads their
inputs, passes a progress callback that persists Run.progress, and stores what they return.
"""

import asyncio
import importlib
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Conflict, ProviderNotConfigured, RateLimited
from app.core.idempotency import idempotency_key_var
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.llm.budget import UsageContext, usage_scope
from app.schemas.evidence import EvidenceRecord
from app.schemas.runs import RunAccepted, RunError, RunProgress, RunResultRef
from app.services.common import get_owned
from app.services.projects import to_brand
from app.services.providers import llm_configured
from app.services.results import API, evidence_by_ids

logger = logging.getLogger("omnicult.runs")

ACTIVE = ("queued", "running")
USABLE = ("completed", "partial")
STAGES: dict[str, tuple[str, ...]] = {
    "transcreate": ("loading_context", "transcreating_lines", "checking_terms", "checking_script"),
    "creative_xray": ("probing_media", "extracting_media", "transcribing", "observing_frames", "structuring_scenes"),
    "remake_visual": ("loading_context", "generating_scene", "rendering_text", "checking_locked_regions"),
    "remake_sound": ("loading_context", "speaking_lines", "making_jingle", "assembling_track"),
}
LABELS = {
    "transcreate": "transcreation",
    "creative_xray": "Creative X-Ray",
    "remake_visual": "Remake: Visuals",
    "remake_sound": "Remake: Sound",
}
ENTRY_POINTS = {
    "transcreate": "run_transcreate",
    "creative_xray": "run_creative_xray",
    "remake_visual": "run_remake_visual",
    "remake_sound": "run_remake_sound",
}
MAX_CONCURRENT_RUNS = 4  # per-process semaphore; a worker queue if runs must survive restarts
RUN_TIMEOUT_SECONDS = 900
RUN_LEASE_SECONDS = 3600  # the longest a run may hold its lease; a sweep may reclaim it afterwards
SHUTDOWN_GRACE_SECONDS = 5


INTERRUPTED = RunError(
    code="RUN_INTERRUPTED",
    message="The server restarted before this run finished. No results were saved; retrying is safe.",
    retryable=True,
)
UNEXPECTED = RunError(
    code="INTERNAL_ERROR",
    message="An unexpected error stopped this run. No results were saved; retrying is safe.",
    retryable=True,
)


class _Executor:
    """Tracks background tasks. Rebinds its asyncio primitives when the event loop changes (tests)."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.tasks: set[asyncio.Task[None]] = set()

    def bind(self) -> "_Executor":
        loop = asyncio.get_running_loop()
        if loop is not self.loop:
            self.loop, self.tasks = loop, set()
            self.slots, self.start_lock = asyncio.Semaphore(MAX_CONCURRENT_RUNS), asyncio.Lock()
        return self

    def submit(self, run_id: UUID, run_type: str) -> None:
        task = asyncio.create_task(_execute(run_id, run_type), name=f"run-{run_id}")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)


executor = _Executor()


def _workflows() -> Any:
    """The AI workstream's package, resolved at call time (via sys.modules, so tests can substitute it)."""
    return importlib.import_module("app.workflows")


def _workflow_types() -> Any:
    return importlib.import_module("app.workflows.types")


# --- starting runs ---------------------------------------------------------------------


def _check_provider(mode: str, run_type: str) -> None:
    if mode == "demo":
        return
    if not llm_configured(get_settings()):
        raise ProviderNotConfigured(
            f"Live {LABELS[run_type]} is unavailable: no language model provider is configured on the server. "
            "Use a demo project or configure Google (Vertex AI or the Gemini API)."
        )


async def _create_run(
    user_id: UUID, project: m.Project, run_type: str, inputs: dict[str, Any], *,
    campaign_id: UUID | None = None, study_id: UUID | None = None,
    extra_rows: Callable[[m.AgentRun], list[Any]] | None = None,
) -> RunAccepted:
    """Record a queued run (plus any resource rows it fills later, same transaction) and start it."""
    _check_provider(project.mode, run_type)
    engine = executor.bind()
    key = idempotency_key_var.get()
    async with engine.start_lock:  # count and insert atomically on this instance
        async with session() as s, s.begin():
            if key is not None:  # a retried request returns the run it already created
                earlier = await s.scalar(
                    select(m.AgentRun).where(m.AgentRun.created_by == user_id, m.AgentRun.idempotency_key == key)
                )
                if earlier is not None:
                    if (earlier.project_id, earlier.run_type) != (project.id, run_type):
                        raise Conflict("This Idempotency-Key was already used for a different request.")
                    return RunAccepted(
                        run_id=earlier.id, status=earlier.status, run_type=run_type,  # type: ignore[arg-type]
                        status_url=f"{API}/runs/{earlier.id}",
                    )
            await _check_active_limit(s, user_id)
            run = m.AgentRun(
                id=uuid4(), project_id=project.id, campaign_id=campaign_id, study_id=study_id, run_type=run_type,
                status="queued", mode=project.mode, inputs=inputs, steps=[], created_at=utcnow(),
                created_by=user_id, idempotency_key=key,
            )
            s.add(run)
            if key is not None:
                try:
                    await s.flush()
                except IntegrityError:  # the same key arrived on another instance at the same moment
                    raise Conflict("A request with this Idempotency-Key is already in progress. Retry shortly.") from None
            await s.execute(update(m.Project).where(m.Project.id == project.id).values(last_activity_at=run.created_at))
            if extra_rows is not None:
                await s.flush()
                s.add_all(extra_rows(run))
                try:
                    await s.flush()
                except IntegrityError:
                    raise Conflict("A concurrent request created the same resource version. Try again.") from None
    engine.submit(run.id, run_type)
    return RunAccepted(run_id=run.id, status="queued", run_type=run_type, status_url=f"{API}/runs/{run.id}")  # type: ignore[arg-type]


async def brand_of(s: AsyncSession, project_id: UUID) -> m.BrandKit:
    return (await s.execute(select(m.BrandKit).where(m.BrandKit.project_id == project_id))).scalar_one()


def brand_context(types: Any, brand: m.BrandKit) -> Any:
    """Brand Memory as the run reads it (all fields; workflows never write it, D-036)."""
    return types.BrandContext.model_validate(to_brand(brand).model_dump(exclude={"id", "updated_at"}))


def merge_terms(*groups: list[str]) -> list[str]:
    merged: dict[str, str] = {}
    for term in (t for group in groups for t in group):
        merged.setdefault(term.casefold(), term)
    return list(merged.values())


# --- executing runs --------------------------------------------------------------------


async def _execute(run_id: UUID, run_type: str) -> None:
    try:
        async with executor.bind().slots:
            if not await _mark_running(run_id, run_type):
                return
            async with asyncio.timeout(RUN_TIMEOUT_SECONDS):
                workflow_input, deps = await _build_input(run_id)
                run_workflow = getattr(_workflows(), ENTRY_POINTS[run_type])
                with usage_scope(await _usage_context(run_id)):  # its model calls are attributed to it and count against its budget
                    outcome = await run_workflow(workflow_input, deps, _progress_callback(run_id))
            await _persist(run_id, outcome)
        await index_project(run_id=run_id)
    except asyncio.CancelledError:
        if await _cancel_requested(run_id):
            await _cancelled(run_id)
        else:
            await _fail(run_id, INTERRUPTED)
        raise
    except TimeoutError:
        limit = RUN_TIMEOUT_SECONDS // 60
        await _fail(
            run_id,
            RunError(
                code="RUN_FAILED", retryable=True,
                message=f"The run exceeded the {limit}-minute limit. No results were saved; retrying is safe.",
            ),
        )
    except Exception:
        logger.exception("Run failed unexpectedly", extra={"run_id": str(run_id), "run_type": run_type})
        await _fail(run_id, UNEXPECTED)


async def _usage_context(run_id: UUID) -> UsageContext:
    """Who a run's model calls are for (ai_usage_events columns)."""
    async with read_session() as s:
        row = (await s.execute(
            select(m.Project.workspace_id, m.AgentRun.project_id, m.AgentRun.campaign_id, m.AgentRun.created_by)
            .join(m.Project, m.Project.id == m.AgentRun.project_id).where(m.AgentRun.id == run_id)
        )).one()
    return UsageContext(workspace_id=row[0], project_id=row[1], campaign_id=row[2], user_id=row[3], run_id=run_id)


async def index_project(*, run_id: UUID | None = None, project_id: UUID | None = None) -> None:
    """Best-effort retrieval indexing after a write (live projects, embeddings configured). Never fails the caller."""
    try:
        from app.retrieval import get_retrieval_service
        from app.services.search import DbRetrievalStore, project_documents, sync_index

        async with read_session() as s:
            if project_id is None:
                run = await s.get(m.AgentRun, run_id)
                project_id = run.project_id if run else None
            project = await s.get(m.Project, project_id) if project_id else None
            if project is None or project.mode != "live":
                return
            store = DbRetrievalStore()
            service = get_retrieval_service("live", get_settings(), store)
            if not service.is_configured():
                return
            documents = await project_documents(s, project.id)
        with usage_scope(UsageContext(workspace_id=project.workspace_id, project_id=project.id)):
            await sync_index(service, store, project.id, documents)
    except Exception:
        logger.warning("Retrieval indexing failed; search re-indexes on its next query", exc_info=True)


async def _mark_running(run_id: UUID, run_type: str) -> bool:
    first = RunProgress(stage=STAGES[run_type][0], completed_steps=0, total_steps=len(STAGES[run_type]), message="Starting.")
    async with session() as s, s.begin():
        result = await s.execute(
            update(m.AgentRun)
            .where(m.AgentRun.id == run_id, m.AgentRun.status == "queued")
            .values(
                status="running", started_at=utcnow(), progress=first.model_dump(),
                heartbeat_at=utcnow(), lease_expires_at=utcnow() + timedelta(seconds=RUN_LEASE_SECONDS),
                attempt=m.AgentRun.attempt + 1,
            )
        )
    return result.rowcount == 1  # type: ignore[attr-defined]


def _progress_callback(run_id: UUID) -> Any:
    async def progress(stage: str, completed_steps: int, total_steps: int, message: str) -> None:
        try:
            value = RunProgress(stage=stage, completed_steps=completed_steps, total_steps=total_steps, message=message)
            async with session() as s, s.begin():
                await s.execute(
                    update(m.AgentRun)
                    .where(m.AgentRun.id == run_id, m.AgentRun.status == "running")
                    .values(progress=value.model_dump())
                )
        except Exception:  # progress is best-effort and must never break the run
            logger.warning("Progress update skipped", extra={"run_id": str(run_id), "stage": stage}, exc_info=True)

    return progress


async def _build_input(run_id: UUID) -> tuple[Any, Any]:
    types, settings = _workflow_types(), get_settings()
    async with read_session() as s:
        run = await s.get(m.AgentRun, run_id)
        assert run is not None
        inputs, brand = run.inputs, await brand_of(s, run.project_id)
        context = types.WorkflowContext(
            run_id=run.id, project_id=run.project_id, campaign_id=run.campaign_id, mode=run.mode,
            brand=brand_context(types, brand),
        )
        grounding = await evidence_by_ids(s, run.project_id, inputs.get("grounding_evidence_ids", []))

        if run.run_type == "transcreate":
            from app.services import transcreate

            workflow_input = await transcreate.build_input(s, run, types, context, grounding)
        elif run.run_type == "creative_xray":
            from app.services import xray

            workflow_input = await xray.build_input(s, run, types, context, grounding)
        elif run.run_type in ("remake_visual", "remake_sound"):
            from app.services import remake

            workflow_input = await remake.build_input(s, run, types, context, grounding)
        else:
            raise ValueError(f"Run type {run.run_type!r} is not executed by the run engine.")
        mode = run.mode
    return workflow_input, _workflows().build_workflow_deps(mode, settings)


# --- persisting outcomes ---------------------------------------------------------------


def _dump(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        return [_dump(item) for item in value]
    return value.model_dump(mode="json")


def _referenced(payload: Any) -> list[str]:
    """Every id listed under an `evidence_ids` key anywhere in a dumped result."""
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            found += [str(i) for i in value] if key == "evidence_ids" and isinstance(value, list) else _referenced(value)
    elif isinstance(payload, list):
        for item in payload:
            found += _referenced(item)
    return found


def _union(*groups: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(i) for group in groups for i in group))


def _evidence_row(run: m.AgentRun, record: EvidenceRecord) -> m.EvidenceRecord:
    if run.mode == "demo" and (record.is_live_data or record.retrieval_mode in ("live", "cached")):
        raise ValueError("A demo run produced evidence labeled as live data; refusing to store it.")
    data = record.model_dump(mode="json")
    return m.EvidenceRecord(
        id=record.id, project_id=run.project_id, source_run_id=record.source_run_id or run.id,
        evidence_type=record.evidence_type, claim_type=record.claim_type, title=record.title, summary=record.summary,
        source_provider=record.source_provider, source_workflow=record.source_workflow,
        source_reference=record.source_reference, subject=data["subject"], related_entity=data["related_entity"],
        attributes=data["attributes"], method=record.method, retrieval_mode=record.retrieval_mode,
        is_live_data=record.is_live_data, retrieved_at=record.retrieved_at, limitations=data["limitations"],
        provenance=data["provenance"], created_at=record.created_at,
    )


def _final_progress(run: m.AgentRun, status: str, error: RunError | None) -> dict[str, Any]:
    stages = STAGES.get(run.run_type, ("loading_context",))  # a stored run of a type this build no longer executes
    total = len(stages)
    if status in USABLE:
        message = "Complete." if status == "completed" else "Finished with partial results; see the limitations."
        if run.mode == "demo":
            message = message[:-1] + " (demo fixtures)."
        return RunProgress(stage="completed", completed_steps=total, total_steps=total, message=message).model_dump()
    current = dict(run.progress or {"stage": stages[0], "completed_steps": 0, "total_steps": total, "message": ""})
    if error is not None and error.stage:
        current["stage"] = error.stage
    return current


async def _persist(run_id: UUID, outcome: Any) -> None:
    now = utcnow()
    async with session() as s, s.begin():
        run = await s.get(m.AgentRun, run_id)
        if run is None or run.status != "running":
            return
        status = outcome.status
        evidence = getattr(outcome, "evidence", [])
        existing = set(
            (await s.execute(select(m.EvidenceRecord.id).where(m.EvidenceRecord.id.in_([e.id for e in evidence])))).scalars()
        )
        new_rows = [_evidence_row(run, e) for e in evidence if e.id not in existing]  # only records new in this run
        s.add_all(new_rows)
        await s.flush()
        new_ids = [str(row.id) for row in new_rows]
        ref: tuple[str, list[Any], str]

        if run.run_type == "transcreate":
            from app.services import transcreate

            payload, ref = await transcreate.persist(s, run, outcome, new_ids, now)
            status = payload.pop("_status", status)  # a refused operation (a lock set meanwhile) is a failed run
        elif run.run_type == "creative_xray":
            from app.services import xray

            payload, ref = await xray.persist(s, run, outcome, new_ids, now)
        elif run.run_type in ("remake_visual", "remake_sound"):
            from app.services import remake

            payload, ref = await remake.persist(s, run, outcome, new_ids, now)
            status = payload.pop("_status", status)  # a refused operation (a lock set meanwhile) is a failed run
        else:
            raise ValueError(f"Run type {run.run_type!r} is not executed by the run engine.")

        error = outcome.error
        if status == "failed" and error is None:
            error = RunError(code="RUN_FAILED", message="The workflow failed without a reported cause.", retryable=True)
        run.result = payload
        run.status = status
        run.result_ref = (
            RunResultRef(resource=ref[0], ids=ref[1], url=ref[2]).model_dump(mode="json")  # type: ignore[arg-type]
            if status in USABLE else None
        )
        run.error = error.model_dump(mode="json") if error else None
        run.steps = _dump(list(outcome.steps))
        run.progress = _final_progress(run, status, error)
        run.completed_at = now
        await s.execute(update(m.Project).where(m.Project.id == run.project_id).values(last_activity_at=now))


async def _fail(run_id: UUID, error: RunError) -> None:
    """Record a terminal failure. Retried briefly: a run left non-terminal would hold the user's run quota."""
    for attempt in range(3):
        try:
            async with session() as s, s.begin():
                run = await s.get(m.AgentRun, run_id)
                if run is not None and run.status in ACTIVE:
                    _mark_failed(run, error)
            return
        except Exception:
            if attempt == 2:
                logger.exception("Could not record run failure", extra={"run_id": str(run_id)})
            else:
                await asyncio.sleep(0.5 * (attempt + 1))


def _mark_failed(run: m.AgentRun, error: RunError) -> None:
    stage = error.stage or (run.progress or {}).get("stage")
    error = error.model_copy(update={"stage": stage})
    run.status, run.result_ref, run.completed_at = "failed", None, utcnow()
    run.error = error.model_dump(mode="json")
    run.progress = _final_progress(run, "failed", error) if run.progress else None


async def mark_interrupted_runs() -> int:
    """Startup sweep: a restart loses in-process runs, so every queued or running run is marked failed (RUN_INTERRUPTED)."""
    try:
        async with session() as s, s.begin():
            rows = (await s.execute(select(m.AgentRun).where(m.AgentRun.status.in_(ACTIVE)))).scalars().all()
            for run in rows:
                _mark_failed(run, INTERRUPTED)
    except Exception:
        logger.exception("Startup sweep failed. Is the database migrated? Run: uv run alembic upgrade head")
        return 0
    if rows:
        logger.warning("Marked interrupted runs as failed", extra={"count": len(rows)})
    return len(rows)


async def _cancel_requested(run_id: UUID) -> bool:
    try:
        async with read_session() as s:
            return bool(await s.scalar(select(m.AgentRun.cancel_requested_at).where(m.AgentRun.id == run_id)))
    except Exception:
        return False


async def _cancelled(run_id: UUID) -> None:
    """Terminal `cancelled`."""
    async with session() as s, s.begin():
        run = await s.get(m.AgentRun, run_id)
        if run is not None and run.status in ACTIVE:
            run.status, run.completed_at, run.error = "cancelled", utcnow(), None
            run.result_ref = None


async def _check_active_limit(s: AsyncSession, user_id: UUID) -> None:
    active = await s.scalar(
        select(func.count(m.AgentRun.id))
        .where(m.AgentRun.created_by == user_id, m.AgentRun.status.in_(ACTIVE))
    )
    limit = get_settings().max_active_runs_per_user
    if (active or 0) >= limit:
        raise RateLimited(f"You already have {active} active runs (limit {limit}). Wait for one to finish, then try again.")


async def cancel_run(user_id: UUID, run_id: UUID) -> Any:
    from app.services.results import to_run

    async with session() as s, s.begin():
        run, _ = await get_owned(s, m.AgentRun, run_id, user_id, "Run")
        if run.status not in ACTIVE:
            raise Conflict(f"The run has already finished ({run.status}).")
        if run.status == "queued":
            run.status, run.completed_at, run.result_ref = "cancelled", utcnow(), None
        else:
            run.cancel_requested_at = utcnow()
    if run.status == "running":  # no checkpoints: stop the task now
        for task in list(executor.bind().tasks):
            if task.get_name() == f"run-{run_id}":
                task.cancel()
    return to_run(run)


async def wait_idle() -> None:
    """Wait until every background run on this loop has finished (tests and shutdown)."""
    engine = executor.bind()
    while engine.tasks:
        await asyncio.wait(list(engine.tasks))


async def shutdown() -> None:
    engine = executor.bind()
    tasks = list(engine.tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.wait(tasks, timeout=SHUTDOWN_GRACE_SECONDS)
