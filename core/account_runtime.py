"""Serialize publication of ownership with in-process capture and notifications."""
import asyncio
from contextlib import asynccontextmanager

_guards = {}


@asynccontextmanager
async def account_guard(account_user_id):
    entry = _guards.setdefault(account_user_id, [asyncio.Lock(), 0])
    entry[1] += 1
    try:
        async with entry[0]:
            yield
    finally:
        entry[1] -= 1
        if not entry[1]:
            _guards.pop(account_user_id, None)
