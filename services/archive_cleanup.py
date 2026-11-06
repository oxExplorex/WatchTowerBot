"""Identify legacy bot dialogs using the public SDK before removing their data."""
import asyncio
import time

from core.logging import bot_logger
from db.repositories.chat_policy_repo import ChatPolicyRepository
from db.session import get_session_factory
from pyrogram.errors import FloodWait, PeerIdInvalid


async def _resolve_users(client, peers, budget):
    if not peers or budget[0] <= 0:
        return []
    budget[0] -= 1
    try:
        users = await client.get_users(peers)
        return list(users) if isinstance(users, (list, tuple)) else [users]
    except PeerIdInvalid:
        if len(peers) == 1:
            return []
        middle = len(peers) // 2
        left = await _resolve_users(client, peers[:middle], budget)
        return left + await _resolve_users(client, peers[middle:], budget)


async def classify_legacy_chats(client, account, limits, *, repository=None):
    if not callable(getattr(client, "get_users", None)):
        return
    if await limits.blocked_until(account.user_id) > int(time.time()):
        return
    repository = repository or ChatPolicyRepository(get_session_factory)
    peers = await repository.claim_unknown(account)
    if not peers:
        return
    try:
        async with asyncio.timeout(30):
            users = await _resolve_users(client, peers, [5])
        # Empty/deleted/inaccessible users may have no bot flag. Keep their data
        # until Telegram supplies a definite answer; a username is not evidence.
        verified = [user for user in users if getattr(user, "id", None) in peers
                    and type(getattr(user, "is_bot", None)) is bool]
        if verified:
            await repository.observe(account.user_id, verified)
        await repository.defer_unknown(account.user_id, peers)
        bot_logger.info("Legacy archive chat types checked: account_user_id=%s checked=%s verified=%s bots=%s",
            account.user_id, len(peers), len(verified), sum(user.is_bot for user in verified))
    except asyncio.CancelledError:
        await repository.defer_unknown(account.user_id, peers, delay=120)
        raise
    except FloodWait as error:
        await limits.defer(account.user_id, int(error.value) + 5)
        await repository.defer_unknown(account.user_id, peers, delay=int(error.value) + 5)
    except Exception as error:
        await repository.defer_unknown(account.user_id, peers)
        bot_logger.debug("Legacy archive type check deferred: account_user_id=%s error=%s",
                         account.user_id, type(error).__name__)
