"""`offline`: demo runs never reach the network or start a subprocess. Import the fixture into a test module to use it."""

import asyncio
from typing import Any

import pytest
import respx


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> Any:
    async def no_subprocess(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("demo runs must not start a subprocess")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_subprocess)
    with respx.mock(assert_all_called=False) as router:  # no route matches, so any outbound request fails
        yield router
