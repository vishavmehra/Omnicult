"""Bearer-token verification.

AUTH_MODE=dev:      `dev-<label>` maps to uuid5(NAMESPACE_URL, "nativeproof-dev:<label>"). Refused in production.
AUTH_MODE=firebase: Firebase Authentication ID tokens, verified here with Google's public keys (rules from
                    https://firebase.google.com/docs/auth/admin/verify-id-tokens, checked 2026-11-17):
                      * header alg RS256, `kid` one of the keys served at the securetoken JWKS endpoint;
                      * `exp` in the future, `iat` and `auth_time` in the past (30 s clock leeway);
                      * `aud` = the Firebase project id, `iss` = https://securetoken.google.com/<project id>;
                      * `sub` a non-empty string (the Firebase uid, at most 128 characters).
                    Anonymous users are marked `firebase.sign_in_provider == "anonymous"`. Token revocation is not
                    checked (the Admin SDK does not check it either by default); tokens live for one hour.

The result is an `Identity`: who the token names. The internal user id is resolved from it by
`app.services.identity.resolve_user`.
"""

import logging
import re
import time
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
import jwt

from app.core.config import Settings
from app.core.errors import Unauthenticated

logger = logging.getLogger("nativeproof.auth")

DEV_TOKEN = re.compile(r"^dev-([A-Za-z0-9_.-]{1,64})$")
FIREBASE_JWKS_URL = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
FIREBASE_ISSUER_PREFIX = "https://securetoken.google.com/"
FIREBASE_ALGORITHM = "RS256"
MAX_UID_LENGTH = 128
JWKS_TTL_SECONDS = 600
JWKS_MIN_REFRESH_SECONDS = 30
JWKS_TIMEOUT_SECONDS = 5
CLOCK_SKEW_SECONDS = 30
INVALID_TOKEN = "The access token is missing, invalid, or expired. Sign in again."


@dataclass(frozen=True)
class Identity:
    """A verified token. Exactly one of `user_id` (dev tokens carry the internal id) and `firebase_uid` is set."""

    user_id: UUID | None = None
    firebase_uid: str | None = None
    is_anonymous: bool = False
    email: str | None = None
    display_name: str | None = None


def dev_user_id(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"nativeproof-dev:{label}")


class JwksCache:
    """Signing keys by kid. Refreshes after the TTL, or early (rate-limited) for an unknown kid."""

    def __init__(self) -> None:
        self.url: str | None = None
        self.keys: dict[str, jwt.PyJWK] = {}
        self.fetched_at = float("-inf")

    async def get(self, url: str, kid: str) -> jwt.PyJWK | None:
        age = time.monotonic() - self.fetched_at
        if url != self.url or age > JWKS_TTL_SECONDS or (kid not in self.keys and age > JWKS_MIN_REFRESH_SECONDS):
            await self._refresh(url)
        return self.keys.get(kid)

    async def _refresh(self, url: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=JWKS_TIMEOUT_SECONDS) as client:
                response = await client.get(url)
                response.raise_for_status()
                entries = response.json().get("keys", [])
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            logger.warning("JWKS fetch failed; keeping cached keys", extra={"error": type(exc).__name__})
            return
        keys: dict[str, jwt.PyJWK] = {}
        for entry in entries:
            try:
                key = jwt.PyJWK(entry)
            except jwt.PyJWTError:
                continue  # unsupported or symmetric entries are skipped
            if entry.get("kid"):
                keys[entry["kid"]] = key
        self.url, self.keys, self.fetched_at = url, keys, time.monotonic()


jwks_cache = JwksCache()


async def verify_bearer_token(token: str, settings: Settings) -> Identity:
    """Return the verified identity or raise Unauthenticated."""
    if settings.auth_mode == "dev":
        match = DEV_TOKEN.match(token)
        if not match:
            raise Unauthenticated(INVALID_TOKEN)
        return Identity(user_id=dev_user_id(match.group(1)))
    return await _verify_firebase(token, settings)


async def _verify_firebase(token: str, settings: Settings) -> Identity:
    project_id = settings.firebase_project_id
    if not project_id:
        logger.error("AUTH_MODE=firebase but FIREBASE_PROJECT_ID is not set; rejecting every token")
        raise Unauthenticated(INVALID_TOKEN)
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise Unauthenticated(INVALID_TOKEN) from None
    kid = header.get("kid")
    if header.get("alg") != FIREBASE_ALGORITHM or not isinstance(kid, str):
        raise Unauthenticated(INVALID_TOKEN)
    jwk = await jwks_cache.get(FIREBASE_JWKS_URL, kid)
    if jwk is None:
        raise Unauthenticated(INVALID_TOKEN)
    try:
        claims = jwt.decode(
            token,
            jwk.key,  # type: ignore[arg-type]
            algorithms=[FIREBASE_ALGORITHM],
            audience=project_id,
            issuer=FIREBASE_ISSUER_PREFIX + project_id,
            leeway=CLOCK_SKEW_SECONDS,
            options={"require": ["exp", "iat", "sub", "aud", "iss", "auth_time"]},
        )
    except jwt.PyJWTError:
        raise Unauthenticated(INVALID_TOKEN) from None
    uid, auth_time = claims.get("sub"), claims.get("auth_time")
    if not isinstance(uid, str) or not uid or len(uid) > MAX_UID_LENGTH:
        raise Unauthenticated(INVALID_TOKEN)
    if not isinstance(auth_time, int | float) or auth_time > time.time() + CLOCK_SKEW_SECONDS:
        raise Unauthenticated(INVALID_TOKEN)
    firebase = claims.get("firebase")
    anonymous = isinstance(firebase, dict) and firebase.get("sign_in_provider") == "anonymous"
    email, name = claims.get("email"), claims.get("name")
    return Identity(
        firebase_uid=uid,
        is_anonymous=anonymous,
        email=email if isinstance(email, str) and email else None,
        display_name=name if isinstance(name, str) and name else None,
    )
