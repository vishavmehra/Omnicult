"""Locally signed Firebase-shaped ID tokens, for exercising AUTH_MODE=firebase without the network."""

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.core import auth

PROJECT = "omnicult-test"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KID = "local-key"


def install_local_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pre-fill the JWKS cache so no request goes to Google."""
    cache = auth.JwksCache()
    jwk = RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True) | {"kid": KID, "alg": "RS256", "use": "sig"}
    cache.url, cache.keys, cache.fetched_at = auth.FIREBASE_JWKS_URL, {KID: jwt.PyJWK(jwk)}, time.monotonic()
    monkeypatch.setattr(auth, "jwks_cache", cache)


def id_token(uid: str, *, anonymous: bool = False, email: str | None = None, name: str | None = None, **extra: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": uid, "aud": PROJECT, "iss": f"https://securetoken.google.com/{PROJECT}", "iat": now - 5,
        "auth_time": now - 5, "exp": now + 3600,
        "firebase": {"sign_in_provider": "anonymous" if anonymous else "google.com", "identities": {}},
    }
    if email:
        claims["email"] = email
    if name:
        claims["name"] = name
    return jwt.encode(claims | extra, KEY, algorithm="RS256", headers={"kid": KID})


def bearer(uid: str, **kwargs: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {id_token(uid, **kwargs)}"}
