"""One raw history page per selected DM, with durable limits and coverage."""
import asyncio
import logging
import time

from pyrogram import raw, utils
from pyrogram.errors import FloodWait

from core.logging import bot_logger
from core.session_manager import SessionUnavailable
from core.session_runtime import session_number_from_client
from core.telegram_errors import is_fatal_session_error
from db.repositories.history_repo import HISTORY_CHAT_LIMIT, HISTORY_PAGE_SIZE, HistoryRepository
from services.history_windows import plan_window
from services.message_service import AccountContext, save_message
from utils.message_payload import enum_value, timestamp


async def _log_peer_cache(client, chat_id):
    if not bot_logger.isEnabledFor(logging.DEBUG):
        return
    lookup = getattr(getattr(client, "storage", None), "get_peer_by_id", None)
    state, peer = "unavailable", None
    if callable(lookup):
        try:
            peer = await lookup(chat_id)
            state = "hit"
        except KeyError:
            state = "miss"
        except Exception as error:
            state = type(error).__name__
    bot_logger.debug("History peer cache: chat_id=%s state=%s peer_type=%s cached_user_id=%s access_hash_present=%s",
        chat_id, state, type(peer).__name__, getattr(peer, "user_id", None),
        getattr(peer, "access_hash", None) not in (None, 0))


async def fetch_history_page(client, chat_id, window):
    if not isinstance(chat_id, int) or chat_id <= 0:
        return None
    await _log_peer_cache(client, chat_id)
    try:
        peer = await client.resolve_peer(chat_id)
    except Exception as error:
        bot_logger.warning("History fetch failed: stage=resolve_peer chat_id=%s error=%s", chat_id, type(error).__name__)
        raise
    bot_logger.debug("History peer resolved: chat_id=%s peer_type=%s resolved_user_id=%s access_hash_present=%s",
        chat_id, type(peer).__name__, getattr(peer, "user_id", None),
        getattr(peer, "access_hash", None) not in (None, 0))
    if not isinstance(peer, (raw.types.InputPeerUser, raw.types.InputPeerSelf)):
        return None
    try:
        response = await client.invoke(raw.functions.messages.GetHistory(
            peer=peer, offset_id=window.offset_id, offset_date=0, add_offset=0,
            limit=HISTORY_PAGE_SIZE, max_id=window.offset_id, min_id=window.low_id - 1, hash=0,
        ), sleep_threshold=0, retries=0)
    except Exception as error:
        bot_logger.warning("History fetch failed: stage=GetHistory chat_id=%s error=%s", chat_id, type(error).__name__)
        raise
    if not hasattr(response, "messages"):
        raise ValueError("Unexpected history response")
    if any(getattr(user, "id", None) == chat_id and getattr(user, "bot", False)
           for user in getattr(response, "users", [])):
        return None
    raw_ids = [item.id for item in response.messages]
    bot_logger.debug("History response: chat_id=%s count=%s first_id=%s last_id=%s",
        chat_id, len(raw_ids), max(raw_ids, default=None), min(raw_ids, default=None))
    if len(raw_ids) > HISTORY_PAGE_SIZE or any(
            item < window.low_id or (window.high_id is not None and item > window.high_id) for item in raw_ids):
        raise ValueError("History response outside requested window")
    messages = await utils.parse_messages(client, response, replies=0)
    for message in messages:
        if not getattr(message, "empty", False) and (
                message.chat is None or message.chat.id != chat_id or enum_value(message.chat.type) != "private"):
            return None
    return raw_ids, [item for item in messages if not getattr(item, "empty", False)]


async def backfill_account(bot, client, account, repository, *, fetch_page=fetch_history_page, save=save_message,
                           pause=asyncio.sleep):
    account = await repository.claim(account.uuid)
    if account is None:
        return
    await repository.seed(account, bot.id)
    context = AccountContext.from_account(account)
    if context is None:
        return
    for index, progress in enumerate(await repository.due_chats(account.uuid)):
        if index >= HISTORY_CHAT_LIMIT:
            break
        if await repository.blocked_until(account.user_id) > int(time.time()):
            break
        if index:
            await pause(3)
        await repository.attempt(progress)
        window = plan_window(progress, await repository.ranges(account.uuid, progress.chat_id), int(time.time()))
        started_at = time.time_ns() // 1000
        bot_logger.debug("History page request: account_uuid=%s owner_id=%s account_user_id=%s chat_id=%s low_id=%s high_id=%s offset_id=%s limit=%s",
            account.uuid, account.admin_id, account.user_id, progress.chat_id,
            window.low_id, window.high_id, window.offset_id, HISTORY_PAGE_SIZE)
        try:
            page = await fetch_page(client, progress.chat_id, window)
            if page is None:
                await repository.attempt(progress, excluded=True, error="NotPrivateChat")
                continue
            raw_ids, messages = page
            if len(raw_ids) > HISTORY_PAGE_SIZE:
                raise ValueError("History page exceeds limit")
            saved_ids = []
            for message in messages:
                edited = getattr(message, "edit_date", None) is not None
                version_at = timestamp(message.edit_date if edited else message.date) or 0
                result = await save(bot, context, message, source="history", kind="edit" if edited else "new",
                                    event_key=f"history:{progress.chat_id}:{message.id}:{version_at}", historical=True)
                if result is None:
                    return  # No checkpoint after revocation, deletion or missing personal key.
                saved_ids.append(message.id)
            await repository.checkpoint(progress, window, raw_ids, saved_ids, started_at)
        except FloodWait as exc:
            await repository.defer(account.user_id, int(exc.value) + 5)
            await repository.attempt(progress, error="FloodWait", delay=int(exc.value) + 5)
            break
        except SessionUnavailable:
            return
        except Exception as exc:
            await repository.attempt(progress, error=type(exc).__name__, delay=60 * 60)
            bot_logger.warning("History page deferred: account_user_id=%s owner_id=%s chat_id=%s error=%s",
                               account.user_id, account.admin_id, progress.chat_id, type(exc).__name__)
            if is_fatal_session_error(exc, include_not_started=True):
                return


async def run_history_backfill(bot, session_manager):
    from db.main import get_account_by_number
    from db.session import get_session_factory

    repository = HistoryRepository(get_session_factory)
    await asyncio.sleep(60)  # Keep login/bootstrap separate from archival traffic.
    while True:
        for client in await session_manager.get_snapshot():
            try:
                if not await session_manager.is_available(client):
                    continue
                if not getattr(client, "_watchtower_dialogs_loaded", False):
                    continue  # Initial dialog scan populates peer/access-hash cache.
                number = session_number_from_client(client)
                account = await get_account_by_number(number) if number else None
                if account is not None:
                    await session_manager.run(client, lambda: backfill_account(bot, client, account, repository))
            except SessionUnavailable:
                pass
            except Exception as exc:
                bot_logger.warning("History worker deferred: %s", type(exc).__name__)
            await asyncio.sleep(3)
        await asyncio.sleep(30)
