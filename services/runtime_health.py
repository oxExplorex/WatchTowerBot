"""Observe existing polling and session state; never issue additional Telegram RPCs."""
import asyncio
import time
from collections import defaultdict

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import GetUpdates

from core.logging import bot_logger
from core.session_runtime import session_number_from_client


class PollingHealth(BaseRequestMiddleware):
    def __init__(self):
        self.last_success = 0
        self.last_failure = 0
        self.failed_since_sample = False
        self.failures = 0

    async def __call__(self, make_request, bot, method):
        if not isinstance(method, GetUpdates):
            return await make_request(bot, method)
        try:
            result = await make_request(bot, method)
        except Exception:
            self.last_failure = time.time()
            self.failed_since_sample = True
            self.failures += 1
            raise
        self.last_success = time.time()
        return result

    def available(self, now):
        if self.failed_since_sample:
            return 0
        if self.last_success and now - self.last_success <= 120 and self.last_success >= self.last_failure:
            return 1
        if self.last_failure:
            return 0
        return None  # No observation is different from a confirmed polling failure.


async def collect_runtime_health(repository, manager, polling, accounts, *, now=None):
    now = int(time.time()) if now is None else int(now)
    failures = polling.failures
    connected = set()
    for client in await manager.get_snapshot():
        if await manager.is_available(client):
            connected.add(session_number_from_client(client))
    scopes = defaultdict(lambda: [0, 0])
    scopes[0] = [0, 0]
    for account in accounts:
        if not account.admin_id:
            continue
        scopes[account.admin_id]  # Disabled-only owners still get an explicit empty observation.
        if not account.is_active:
            continue
        ready = int(account.number in connected)
        for scope in {0, account.admin_id}:
            scopes[scope][0] += 1
            scopes[scope][1] += ready
    observations = [("userbot", owner_id, *counts) for owner_id, counts in scopes.items()]
    bot_ready = polling.available(now)
    if bot_ready is not None:
        observations.append(("bot", 0, 1, bot_ready))
    await repository.record(observations, now=now)
    polling.failed_since_sample = polling.failures != failures


async def run_runtime_health(manager, polling):
    from db.main import get_account_all
    from db.repositories.runtime_health_repo import RuntimeHealthRepository
    from db.session import get_session_factory

    repository = RuntimeHealthRepository(get_session_factory)
    while True:
        try:
            await collect_runtime_health(repository, manager, polling, await get_account_all())
        except Exception as exc:
            bot_logger.warning("Runtime health observation deferred: %s", type(exc).__name__)
        await asyncio.sleep(60)
