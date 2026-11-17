"""Shared helpers for culture tests: no test here may reach the network.

`replay_client` answers from exchanges recorded against the live services on the date stored in each fixture file
(tests/fixtures/culture/*.json); an unrecorded request fails the test loudly instead of going out.
"""

import json
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "culture"
UA = "CultureTestClient/0.0 (tests)"


def load_recording(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def replay_client(name: str, *, extra: list[dict[str, Any]] | None = None) -> httpx.AsyncClient:
    exchanges = {e["url"]: e for e in [*load_recording(name)["exchanges"], *(extra or [])]}

    def handler(request: httpx.Request) -> httpx.Response:
        exchange = exchanges.get(str(request.url))
        if exchange is None:
            raise AssertionError(f"unrecorded request in {name}: {request.url}")
        return httpx.Response(exchange["status"], json=exchange["response"])

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def scripted_client(responses: list[httpx.Response | Exception], seen: list[httpx.Request] | None = None) -> httpx.AsyncClient:
    """Answers each request with the next scripted response (or raises the scripted exception)."""
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def no_sleep(_: float) -> None:
    return None
