from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any

from core.logging import bot_logger


def _task_done_callback(task: asyncio.Task[Any]) -> None:
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
    task.add_done_callback(_task_done_callback)
    return task
