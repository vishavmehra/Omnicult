"""Authentication: dev tokens through the API, and Firebase ID token verification with local keys (no network)."""

import time
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.core import auth
from app.core.config import Settings
from app.core.errors import Unauthenticated

PROJECT = "omnicult-test"
ISSUER = f"https://securetoken.google.com/{PROJECT}"
UID = "firebase-uid-123"


async def test_missing_and_malformed_tokens_are_401(client: httpx.AsyncClient) -> None:
    for headers in ({"Authorization": ""}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic dev-alice"}):
        response = await client.get("/api/v1/projects", headers=headers)
        assert response.status_code == 401, headers
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_dev_token_maps_to_stable_uuid5() -> None:
    assert auth.dev_user_id("local") == uuid5(NAMESPACE_URL, "omnicult-dev:local")


async def test_dev_token_yields_an_identity_with_the_internal_id() -> None:
    identity = await auth.verify_bearer_token("dev-local", Settings(_env_file=None, auth_mode="dev"))  # type: ignore[call-arg]
    assert identity == auth.Identity(user_id=auth.dev_user_id("local"))


# --- Firebase mode ------------------------------------------------------------------------

RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwks() -> dict[str, Any]:
    jwk = RSAAlgorithm.to_jwk(RSA_KEY.public_key(), as_dict=True) | {"kid": "key-1", "alg": "RS256", "use": "sig"}
    return {"keys": [jwk]}


def claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    base = {
        "sub": UID, "aud": PROJECT, "iss": ISSUER, "iat": now - 5, "auth_time": now - 5, "exp": now + 3600,
        "firebase": {"sign_in_provider": "google.com", "identities": {}},
        "email": "ada@example.com", "name": "Ada",
    }
    return {k: v for k, v in (base | overrides).items() if v is not None}


def token(payload: dict[str, Any] | None = None, key: Any = RSA_KEY, kid: str = "key-1", alg: str = "RS256") -> str:
    return jwt.encode(payload if payload is not None else claims(), key, algorithm=alg, headers={"kid": kid})


def settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, auth_mode="firebase", firebase_project_id=PROJECT, **overrides)  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def fresh_jwks_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "jwks_cache", auth.JwksCache())


@respx.mock
async def test_valid_firebase_token_yields_uid_email_and_name() -> None:
    route = respx.get(auth.FIREBASE_JWKS_URL).mock(return_value=httpx.Response(200, json=jwks()))
    identity = await auth.verify_bearer_token(token(), settings())
    assert identity == auth.Identity(firebase_uid=UID, is_anonymous=False, email="ada@example.com", display_name="Ada")
    await auth.verify_bearer_token(token(), settings())
    assert route.call_count == 1  # keys are cached


@respx.mock
async def test_anonymous_sign_in_is_detected() -> None:
    respx.get(auth.FIREBASE_JWKS_URL).mock(return_value=httpx.Response(200, json=jwks()))
    anonymous = token(claims(firebase={"sign_in_provider": "anonymous", "identities": {}}, email=None, name=None))
    identity = await auth.verify_bearer_token(anonymous, settings())
    assert identity.is_anonymous is True and identity.email is None and identity.firebase_uid == UID


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 120},
        {"aud": "another-project"},
        {"iss": "https://securetoken.google.com/another-project"},
        {"iss": "https://accounts.google.com"},
        {"sub": ""},
        {"sub": "x" * 129},
        {"sub": 12345},
        {"iat": int(time.time()) + 3600},
        {"auth_time": int(time.time()) + 3600},
        {"auth_time": None},
        {"iat": None},
        {"exp": None},
    ],
    ids=["expired", "wrong-audience", "wrong-project-issuer", "wrong-issuer", "empty-sub", "long-sub", "numeric-sub",
         "future-iat", "future-auth-time", "missing-auth-time", "missing-iat", "missing-exp"],
)
@respx.mock
async def test_invalid_claims_are_rejected(overrides: dict[str, Any]) -> None:
    respx.get(auth.FIREBASE_JWKS_URL).mock(return_value=httpx.Response(200, json=jwks()))
    with pytest.raises(Unauthenticated):
        await auth.verify_bearer_token(token(claims(**overrides)), settings())


@respx.mock
async def test_bad_signature_unknown_kid_wrong_algorithm_and_tampering_are_rejected() -> None:
    respx.get(auth.FIREBASE_JWKS_URL).mock(return_value=httpx.Response(200, json=jwks()))
    good = token()
    header, _, signature = good.split(".")
    forged_payload = jwt.utils.base64url_encode(b'{"sub":"someone-else"}').decode()
    for bad in (
        token(key=OTHER_KEY),  # signed with a key Google does not serve
        token(kid="unknown"),
        f"{header}.{forged_payload}.{signature}",
        jwt.encode(claims(), key="", algorithm="none"),
        jwt.encode(claims(), "a-shared-secret-that-is-long-enough-32b", algorithm="HS256", headers={"kid": "key-1"}),
        "not.a.jwt",
        "",
    ):
        with pytest.raises(Unauthenticated):
            await auth.verify_bearer_token(bad, settings())


@respx.mock
async def test_jwks_outage_rejects_without_crashing() -> None:
    respx.get(auth.FIREBASE_JWKS_URL).mock(return_value=httpx.Response(503))
    with pytest.raises(Unauthenticated):
        await auth.verify_bearer_token(token(), settings())


async def test_firebase_mode_without_a_project_id_rejects_everything() -> None:
    unconfigured = Settings(_env_file=None, auth_mode="firebase")  # type: ignore[call-arg]
    with pytest.raises(Unauthenticated):
        await auth.verify_bearer_token("x.y.z", unconfigured)
