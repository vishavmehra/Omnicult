"""The `offline` fixture: outbound HTTP and subprocesses fail, so a pass also shows that demo runs never reach a provider."""

import asyncio
from typing import Any

import pytest
import respx


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> Any:
    async def no_subprocess(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("demo runs must not start a subprocess")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_subprocess)
    with respx.mock(assert_all_called=False) as router:  # any outbound request fails: no route matches
        yield router
