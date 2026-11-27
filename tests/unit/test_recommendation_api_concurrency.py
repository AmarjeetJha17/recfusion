from __future__ import annotations

from threading import Event
from typing import NoReturn

import anyio
import pytest
from anyio import CapacityLimiter

pytestmark = pytest.mark.unit


def _run_with_capacity():
    from recfusion_api.dependencies.recommendation import run_with_capacity

    return run_with_capacity


def test_inference_capacity_is_released_after_exception() -> None:
    limiter = CapacityLimiter(1)
    run_with_capacity = _run_with_capacity()

    def fail() -> NoReturn:
        raise RuntimeError("inference failed")

    async def invoke() -> None:
        with pytest.raises(RuntimeError, match="inference failed"):
            await run_with_capacity(fail, limiter)

    anyio.run(invoke)

    assert limiter.borrowed_tokens == 0


def test_inference_capacity_is_released_after_cancellation() -> None:
    limiter = CapacityLimiter(1)
    run_with_capacity = _run_with_capacity()
    started = Event()
    release = Event()

    def blocking() -> str:
        started.set()
        if not release.wait(timeout=4):
            raise RuntimeError("test release event timed out")
        return "finished"

    async def invoke() -> None:
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(run_with_capacity, blocking, limiter)
            with anyio.fail_after(3):
                while not started.is_set():
                    await anyio.sleep(0.001)
            task_group.cancel_scope.cancel()
            release.set()

    anyio.run(invoke)

    assert limiter.borrowed_tokens == 0
