"""Conversation delivery route regressions."""

import asyncio
import json

import pytest

from backend.routes.conversations import _progress_stream


@pytest.mark.asyncio
async def test_progress_stream_survives_idle_poll_timeout():
    queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()

    async def deliver_after_first_poll() -> None:
        await asyncio.sleep(0.06)
        await queue.put({"type": "step_complete"})

    task = asyncio.create_task(deliver_after_first_poll())
    events = [event async for event in _progress_stream(task, queue)]

    await task
    assert [json.loads(event.removeprefix("data: ")) for event in events] == [
        {"type": "step_complete"}
    ]
