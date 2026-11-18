"""Authorisation for calls from Cloud Scheduler to the internal endpoints.

Cloud Scheduler signs each call with a Google OIDC ID token minted for a service account and an audience. The token is
verified with google-auth (`id_token.verify_oauth2_token`: signature against Google's public keys, issuer, expiry and the
audience), and then the caller must be exactly the configured service account with a verified email.

The endpoint is never open: with `SCHEDULER_SERVICE_ACCOUNT` or `SCHEDULER_AUDIENCE` unset every call is refused (403), a
missing or invalid token is a 401, and a valid Google token from any other account is a 403. Tests replace `get_verifier`
with a fake; nothing in the test suite reaches the network.
"""

import asyncio
import logging
from collections.abc import Callable, Mapping
from typing import Annotated, Any

from fastapi import Depends, Header
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.core.config import get_settings
from app.core.errors import Forbidden, Unauthenticated

logger = logging.getLogger("omnicult.scheduler_auth")

Verifier = Callable[[str, str], Mapping[str, Any]]
NOT_CONFIGURED = "Scheduled evaluation is not enabled on this server."
INVALID_TOKEN = "The scheduler token is missing, invalid, or expired."
WRONG_CALLER = "This service account is not allowed to run scheduled evaluation."


def google_verifier(token: str, audience: str) -> Mapping[str, Any]:
    """Verify a Google-signed ID token and return its claims. Blocking: it fetches Google's signing certificates."""
    return id_token.verify_oauth2_token(token, google_requests.Request(), audience=audience)


def get_verifier() -> Verifier:
    return google_verifier


async def require_scheduler(
    authorization: Annotated[str | None, Header()] = None, verifier: Verifier = Depends(get_verifier),
) -> str:
    """The verified service account email of the caller. Raises 403 when not configured, 401 for a bad token."""
    settings = get_settings()
    account, audience = settings.scheduler_service_account, settings.scheduler_audience
    if not account or not audience:
        raise Forbidden(NOT_CONFIGURED)
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthenticated(INVALID_TOKEN)
    try:
        claims = await asyncio.to_thread(verifier, token.strip(), audience)
    except Exception as error:  # ValueError for a bad token; a transport error when Google's keys cannot be fetched
        logger.warning("scheduler token rejected: %s", type(error).__name__)
        raise Unauthenticated(INVALID_TOKEN) from None
    email = str(claims.get("email") or "")
    if claims.get("email_verified") is not True or email.lower() != account.lower():
        raise Forbidden(WRONG_CALLER)
    return email


google_oidc_verifier = google_verifier  # the digest stream's name for the same verifier
