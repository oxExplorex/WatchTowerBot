"""Bounded DM history batches, with durable limits and coverage."""
import asyncio
import time

from pyrogram.errors import FloodWait

from core.logging import bot_logger
from core.session_manager import SessionUnavailable
from core.session_runtime import session_number_from_client
from core.telegram_errors import is_fatal_session_error
from db.repositories.history_repo import HISTORY_CHAT_LIMIT, HISTORY_PAGE_SIZE, HistoryRepository
from services.history_windows import plan_window
from services.message_service import AccountContext, save_message
from utils.message_payload import enum_value, timestamp


async def fetch_history_page(client, chat_id, window):
    if not isinstance(chat_id, int) or chat_id <= 0:
        return None
    observed_ids, messages = [], []
    # Kurigram's public bounds are inclusive; pagination and parsing belong to the SDK.
    async for message in client.get_chat_history(
            chat_id, limit=HISTORY_PAGE_SIZE, min_id=window.low_id, max_id=window.high_id or 0):
        if len(observed_ids) >= HISTORY_PAGE_SIZE or message.id < window.low_id or (
                window.high_id is not None and message.id > window.high_id):
            raise ValueError("History response outside requested window")
        observed_ids.append(message.id)
        if getattr(message, "empty", False):
            continue
        if message.chat is None or message.chat.id != chat_id or enum_value(message.chat.type) != "private":
            return None
        messages.append(message)
    return observed_ids, messages


async def backfill_account(bot, client, account, repository, *, fetch_page=fetch_history_page, save=save_message,
                           pause=asyncio.sleep):
    account = await repository.claim(account.uuid)
    if account is None:
        return
    await repository.seed(account, bot.id)
    context = AccountContext.from_account(account)
    if context is None:
        return
    checked = processed = failed = 0
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
        checked += 1
        stage = "get_chat_history"
        try:
            page = await fetch_page(client, progress.chat_id, window)
            if page is None:
                await repository.attempt(progress, excluded=True, error="NotPrivateChat")
                continue
            raw_ids, messages = page
            if len(raw_ids) > HISTORY_PAGE_SIZE:
                raise ValueError("History page exceeds limit")
            saved_ids = []
            stage = "save_messages"
            for message in messages:
                edited = getattr(message, "edit_date", None) is not None
                version_at = timestamp(message.edit_date if edited else message.date) or 0
                result = await save(bot, context, message, source="history", kind="edit" if edited else "new",
                                    event_key=f"history:{progress.chat_id}:{message.id}:{version_at}", historical=True)
                if result is None:
                    return  # No checkpoint after revocation, deletion or missing personal key.
                saved_ids.append(message.id)
            stage = "checkpoint"
            await repository.checkpoint(progress, window, raw_ids, saved_ids, started_at)
            processed += len(saved_ids)
            if callable(getattr(client, "get_chat", None)):
                from services.avatar_archive import collect_chat_avatar
                await collect_chat_avatar(bot, client, account, progress.chat_id, limits=repository)
        except FloodWait as exc:
            failed += 1
            await repository.defer(account.user_id, int(exc.value) + 5)
            await repository.attempt(progress, error="FloodWait", delay=int(exc.value) + 5)
            break
        except SessionUnavailable:
            return
        except Exception as exc:
            failed += 1
            await repository.attempt(progress, error=type(exc).__name__, delay=60 * 60)
            bot_logger.warning("History page deferred: account_user_id=%s owner_id=%s chat_id=%s stage=%s error=%s range=%s..%s",
                account.user_id, account.admin_id, progress.chat_id, stage,
                type(exc).__name__, window.low_id, window.high_id)
            if is_fatal_session_error(exc, include_not_started=True):
                return
    if checked:
        bot_logger.info("History pass: account_user_id=%s chats=%s messages_processed=%s deferred=%s",
                        account.user_id, checked, processed, failed)


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
