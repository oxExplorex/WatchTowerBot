from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from core.logging import bot_logger

_background_tasks: set[asyncio.Task[Any]] = set()


def _task_done_callback(task: asyncio.Task[Any]) -> None:
    _background_tasks.discard(task)
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    except Exception:
        bot_logger.exception("Failed to inspect background task result")
        return

    if exc is None:
        return

    bot_logger.exception("Unhandled exception in background task", exc_info=exc)


def create_logged_task(coro: Awaitable[Any], *, name: str | None = None) -> asyncio.Task[Any]:
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_task_done_callback)
    return task


def tracked_job(function: Callable[..., Awaitable[Any]]):
    """Include scheduler jobs in application shutdown, without owning the scheduler."""
    @wraps(function)
    async def wrapped(*args, **kwargs):
        task = asyncio.current_task()
        assert task is not None
        _background_tasks.add(task)
        try:
            return await function(*args, **kwargs)
        finally:
            _background_tasks.discard(task)
    return wrapped


@tracked_job
async def track_update_task(handler, event, data):
    return await handler(event, data)


async def cancel_logged_tasks() -> None:
    current = asyncio.current_task()
    tasks = [task for task in _background_tasks if task is not current and not task.done()]
    for task in tasks:
        if not task.cancelling():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
