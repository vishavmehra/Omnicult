"""Request dependencies shared by every route.

`get_current_user` verifies the bearer token (a Firebase ID token, or the development-only dev token), maps it to the
internal user id (creating the user and a personal workspace on first sign-in), and never exposes the Firebase uid.
"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth import INVALID_TOKEN, verify_bearer_token
from app.core.config import get_settings
from app.core.errors import Forbidden, Unauthenticated, ValidationFailed
from app.core.idempotency import IDEMPOTENCY_HEADER, VALID_KEY, idempotency_key_var
from app.schemas.common import ErrorDetail
from app.services.identity import resolve_user

bearer_scheme = HTTPBearer(auto_error=False)
ANONYMOUS = "Sign in with an account to use this. Anonymous visitors can only explore the demo."


@dataclass(frozen=True)
class AuthUser:
    """The authenticated caller. `id` is the internal `users.id` (never a provider uid)."""

    id: UUID
    is_anonymous: bool = False


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthUser:
    if credentials is None or not credentials.credentials:
        raise Unauthenticated(INVALID_TOKEN)
    identity = await verify_bearer_token(credentials.credentials, get_settings())
    user = await resolve_user(identity)
    return AuthUser(id=user.id, is_anonymous=user.is_anonymous)


async def get_registered_user(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
    """A signed-in (non-anonymous) caller. Anonymous Firebase users may only explore the demo."""
    if user.is_anonymous:
        raise Forbidden(ANONYMOUS)
    return user


async def capture_idempotency_key(
    key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER, include_in_schema=False)] = None,
) -> None:
    """Read the optional Idempotency-Key header for run creation (see app.core.idempotency)."""
    if key is not None and not VALID_KEY.match(key):
        raise ValidationFailed(
            "The supplied request is invalid.",
            details=[ErrorDetail(field=IDEMPOTENCY_HEADER, message="Use 1 to 128 letters, digits, and _ . : -")],
        )
    idempotency_key_var.set(key)


CurrentUser = Annotated[AuthUser, Depends(get_current_user)]
RegisteredUser = Annotated[AuthUser, Depends(get_registered_user)]
Limit = Annotated[int, Query(ge=1, le=100, description="Maximum records returned.")]
Offset = Annotated[int, Query(ge=0, description="Number of records skipped.")]
