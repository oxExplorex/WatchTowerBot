"""Wait for thread-owned mutations before releasing their async resources."""
import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


async def run_blocking(function: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Keep resource locks held until a non-cancellable thread actually finishes."""
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled():
            task.exception()  # Retrieve a worker failure; cancellation still wins.
        raise
