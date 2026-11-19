import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.api.routes import (
    ERROR_RESPONSES,
    assets,
    audience,
    brand,
    campaigns,
    conflicts,
    delivery,
    desk,
    country_packs,
    direct,
    digest,
    evidence,
    generate,
    graph,
    health,
    lab_t3,
    launch,
    lens,
    lens_t3,
    state_facts,
    media,
    projects,
    pulse,
    pulse_t3,
    proof,
    regions,
    remake,
    runs,
    search,
    studio,
    teams,
    studio_t3,
    workspaces,
)
from app.api.deps import capture_idempotency_key
from app.core.config import Settings, get_settings
from app.core.errors import REQUEST_ID_HEADER, RequestContextMiddleware, install_error_handlers
from app.core.logging import configure_logging
from app.db.session import dispose_engine
from app.llm import google
from app.llm.budget import get_default_usage_sink, set_default_usage_sink
from app.media.ffmpeg import log_startup_tools
from app.services import runs as run_engine
from app.services.metering import DbUsageSink

ROUTERS = (
    workspaces,
    regions,
    conflicts,
    projects,
    brand,
    campaigns,
    desk,
    audience,
    lab_t3,
    evidence,
    graph,
    launch,
    delivery,
    lens,
    lens_t3,
    state_facts,
    pulse,
    pulse_t3,
    digest,
    search,
    assets,
    media,
    proof,
    runs,
    studio,
    teams,
    country_packs,
    direct,
    remake,
    generate,
    studio_t3,
)

API_PREFIX = "/api/v1"


def _operation_id(route: APIRoute) -> str:
    return route.name


async def warm_google_credentials() -> None:
    """Load the Application Default Credentials off the event loop at startup (and share them with every client), so the
    first AI request does not wait on the lookup. Best effort: a failure is logged and the first call reports it."""
    settings = get_settings()
    if not google.is_configured(settings):
        return
    try:
        await google.warm_credentials(settings)
    except Exception as exc:
        logging.getLogger(__name__).warning("Google credentials could not be loaded at startup", extra={"error": type(exc).__name__})


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await run_engine.mark_interrupted_runs()
    await log_startup_tools()  # ffmpeg and ffprobe: detected once, logged; video features degrade clearly if absent
    previous = get_default_usage_sink()
    set_default_usage_sink(DbUsageSink())  # every gateway call is stored in ai_usage_events and budgets read it back
    warming = asyncio.create_task(warm_google_credentials())  # in the background: the API serves requests meanwhile
    yield
    warming.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await warming
    set_default_usage_sink(previous)
    await run_engine.shutdown()
    await dispose_engine()


def check_production(settings: Settings) -> None:
    """Fail closed: refuse to start a production app without real auth, a real database, and explicit origins.
    (AUTH_MODE=dev under APP_ENV=production is already refused when the settings load.)"""
    problems = []
    if settings.auth_mode != "firebase" or not settings.firebase_project_id:
        problems.append("AUTH_MODE=firebase with FIREBASE_PROJECT_ID set")
    if not settings.database_url.startswith("postgresql"):
        problems.append("DATABASE_URL pointing at Postgres (SQLite is for development and tests)")
    if not settings.cors_origins or "*" in settings.cors_origins:
        problems.append("FRONTEND_ORIGINS listing explicit origins")
    if problems:
        raise RuntimeError("APP_ENV=production requires: " + "; ".join(problems) + ".")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    production = settings.app_env == "production"
    if production:
        check_production(settings)
    # Interactive docs are a development aid; production serves only the API, /health, and /ready.
    docs = {"docs_url": None, "redoc_url": None, "openapi_url": None} if production else {}
    app = FastAPI(
        title="Omnicult API", version="0.1.0", generate_unique_id_function=_operation_id, lifespan=lifespan, **docs
    )
    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", REQUEST_ID_HEADER],
        expose_headers=[
            REQUEST_ID_HEADER, "Content-Disposition", "X-Omnicult-Shaping", "X-Omnicult-Text-Fit",
            "X-Omnicult-Overlaps-Locked", "X-Omnicult-Locked-Restored",
        ],
    )
    app.include_router(health.router)
    api = APIRouter(prefix=API_PREFIX, responses=ERROR_RESPONSES, dependencies=[Depends(capture_idempotency_key)])
    for module in ROUTERS:
        api.include_router(module.router)
    app.include_router(api)
    return app


app = create_app()
