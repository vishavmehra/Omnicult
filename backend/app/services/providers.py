"""Configuration-level provider status and readiness. Never makes a provider call."""

import asyncio
import logging

from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.db.session import get_engine
from app.llm.gateway import LLMGateway
from app.schemas.health import Readiness, ReadinessCapabilities, ReadinessDependencies

logger = logging.getLogger("omnicult.providers")
DB_CHECK_TIMEOUT_SECONDS = 10  # a cold TLS connection to a remote database can take several seconds


def llm_configured(settings: Settings) -> bool:
    """Google credentials plus a default model; constructing the gateway makes no request."""
    return LLMGateway(settings).is_configured()


async def database_available() -> bool:
    try:
        async with asyncio.timeout(DB_CHECK_TIMEOUT_SECONDS), get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # any failure means "unavailable"; details stay in the log
        logger.warning("Database readiness check failed", extra={"error": type(exc).__name__})
        return False


def capability_statuses(settings: Settings) -> dict[str, str]:
    """From the modality adapters' own is_configured() (a model verified for that capability), never from settings
    alone. Reranking has no adapter, so it is never reported as configured. No call is made."""
    gateway = LLMGateway(settings)
    adapters = {"embeddings": "embeddings", "vision": "vision"}
    statuses = {name: "configured" if gateway.capability(adapter) is not None else "not_configured"
                for name, adapter in adapters.items()}
    return statuses | {"reranking": "not_configured"}


async def readiness() -> Readiness:
    settings = get_settings()
    database, llm = await database_available(), llm_configured(settings)
    live = database and llm
    capabilities = capability_statuses(settings)

    def status(capability: str) -> str:
        return capabilities[capability]

    return Readiness(
        status="not_ready" if not database else "ready" if live else "degraded",
        dependencies=ReadinessDependencies(
            database="available" if database else "unavailable",
            llm_provider="configured" if llm else "not_configured",
        ),
        capabilities=ReadinessCapabilities(
            embeddings=status("embeddings"), vision=status("vision"),  # type: ignore[arg-type]
            reranking=status("reranking"),  # type: ignore[arg-type]
        ),
        live_mode_available=live,
        demo_mode_available=database,
    )
