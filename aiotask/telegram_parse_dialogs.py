import asyncio
import hashlib
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import html
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client
from pyrogram.errors import FloodWait, InternalServerError, RPCError

import data.text as constant_text
from core.logging import bot_logger
from core.session_runtime import remove_client_from_runtime, session_number_from_client
from db.main import (
    add_account_health_event,
    add_chat_history_event,
    create_dump_chat_user,
    del_dump_chat_user,
    delete_account_by_number,
    get_account_by_number,
    get_dump_chat_admin_all,
    get_user,
    update_account_uuid,
    update_user,
)
from loader import apps_session, bot
from utils.datetime_tools import DateTime
from utils.others import get_user_log_text

scheduler = AsyncIOScheduler()
FULL_SCAN_FORCE_INTERVAL_SEC = 60 * 60 * 24
MASS_DELETE_MIN_EXISTING = 20
MASS_DELETE_MIN_COUNT = 10
MASS_DELETE_MIN_RATIO = 0.25

FATAL_SESSION_ERROR_NAMES = {
    "AuthKeyDuplicated",
    "AuthKeyInvalid",
    "AuthKeyPermEmpty",
    "AuthKeyUnregistered",
    "SessionExpired",
    "SessionPasswordNeeded",
    "SessionRevoked",
    "Unauthorized",
    "UserDeactivated",
    "UserDeactivatedBan",
}


async def safe_call(
    coro_func: Callable[..., Awaitable[Any]],
    *args: Any,
    retries: int = 3,
    delay: int = 2,
    **kwargs: Any,
) -> Any:
    last_error: Exception | None = None
    for i in range(retries):
        try:
            return await coro_func(*args, **kwargs)
        except FloodWait as exc:
            last_error = exc
            bot_logger.warning(f"FloodWait: sleeping for {exc.value} seconds")
            await asyncio.sleep(exc.value)
        except (RPCError, InternalServerError) as exc:
            last_error = exc
            bot_logger.warning(f"Attempt {i + 1}/{retries} failed: {type(exc).__name__} - {exc}")
            await asyncio.sleep(delay * (2**i))

    bot_logger.error(f"All retries failed for {coro_func.__name__}")
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"safe_call: all retries failed for {coro_func.__name__}")


def chunk_text(messages: list[str], max_length: int = 3500) -> list[str]:
    result, current = [], ""
    for msg in messages:
        if len(current) + len(msg) >= max_length:
            result.append(current)
            current = ""
        current += msg
    if current:
        result.append(current)
    return result


def _is_fatal_session_error(exc: Exception) -> bool:
    if exc.__class__.__name__ in FATAL_SESSION_ERROR_NAMES:
        return True

    error_text = str(exc).lower()
    fatal_markers = (
        "auth key unregistered",
        "auth key invalid",
        "session revoked",
        "session expired",
        "unauthorized",
        "user deactivated",
        "client has not been started yet",
    )
    return any(marker in error_text for marker in fatal_markers)


def _is_bot_or_channel(chat_obj) -> bool:
    chat_type = str(getattr(chat_obj, "type", "")).lower()
    return "bot" in chat_type or "channel" in chat_type


def _ids_signature(ids: set[int]) -> str:
    if not ids:
        return ""
    payload = ",".join(str(x) for x in sorted(ids))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _drop_dead_session(app_session: Client, error: Exception) -> None:
    number = session_number_from_client(app_session)
    bot_logger.error(f"Session dropped: {number or constant_text.UNKNOWN_TEXT} | {error.__class__.__name__}: {error}")

    if app_session in apps_session:
        await remove_client_from_runtime(app_session)

    if not number:
        return

    account = await get_account_by_number(number)
    if not account:
        bot_logger.warning(f"Failed to find account in DB for dead session number={number}")
        return

    await add_account_health_event(
        account_uuid=account.uuid,
        admin_id=account.admin_id,
        user_id=account.user_id,
        status=0,
        date=DateTime().timestamp(),
        reason=f"drop:{error.__class__.__name__}",
    )
    await delete_account_by_number(number)

    if not account.admin_id:
        return

    try:
        await bot.send_message(
            chat_id=account.admin_id,
            text=constant_text.PARSER_SESSION_DROPPED_TEXT.format(
                number=html.quote(str(account.number or constant_text.UNKNOWN_TEXT))
            ),
        )
    except Exception:
        bot_logger.error(traceback.format_exc())


@scheduler.scheduled_job("interval", minutes=20)
async def __tg_parse_dialogs_handler() -> None:
    try:
        if not apps_session:
            bot_logger.warning("apps_session is empty - no active user sessions to scan")
            return

        runtime_sessions: list[Client] = [app for app in apps_session if isinstance(app, Client)]

        for app_session in runtime_sessions:
            # Yield control between sessions to keep the event loop responsive.
            await asyncio.sleep(0)
            account_settings = None
            try:
                session_number = session_number_from_client(app_session)
                account_settings = await get_account_by_number(session_number) if session_number else None

                if not account_settings:
                    await remove_client_from_runtime(app_session)
                    continue

                if not account_settings.is_active:
                    continue

                user_id = int(account_settings.user_id)
                now_ts = DateTime().timestamp()
                total_dialogs = int(await safe_call(app_session.get_dialogs_count) or 0)

                previous_count = int(getattr(account_settings, "last_dialogs_count", -1) or -1)
                last_full_scan = int(getattr(account_settings, "last_full_dialogs_scan", 0) or 0)

                should_full_scan = (
                    previous_count < 0
                    or total_dialogs != previous_count
                    or (now_ts - last_full_scan) >= FULL_SCAN_FORCE_INTERVAL_SEC
                )

                if not should_full_scan:
                    bot_logger.debug(
                        f"Skip full scan for {user_id}: dialogs_count unchanged ({total_dialogs}), "
                        f"last_full_scan={last_full_scan}"
                    )
                    await update_account_uuid(
                        account_settings.uuid,
                        account_settings.admin_id,
                        last_update=now_ts,
                        last_dialogs_count=total_dialogs,
                    )
                    await add_account_health_event(
                        account_uuid=account_settings.uuid,
                        admin_id=account_settings.admin_id,
                        user_id=account_settings.user_id,
                        status=1,
                        date=now_ts,
                        reason="count_only",
                    )
                    continue

                bot_logger.info(f"FULL SCAN USER: {user_id} | dialogs_count={total_dialogs}")

                existing_chat_ids = {x.chat_id for x in await get_dump_chat_admin_all(user_id)}
                current_chat_ids = set()
                seen_chat_ids = set()
                new_chats = []
                filtered_out_count = 0

                try:
                    scanned_count = 0
                    async for dialog in app_session.get_dialogs(limit=total_dialogs + 15):
                        scanned_count += 1
                        if scanned_count % 100 == 0:
                            # Long scans should not monopolize the loop.
                            await asyncio.sleep(0)
                        chat = dialog.chat
                        chat_id = chat.id
                        seen_chat_ids.add(chat_id)

                        if not account_settings.alert_bot and _is_bot_or_channel(chat):
                            filtered_out_count += 1
                            continue

                        username = chat.username
                        chat_name = chat.full_name or chat.title

                        if chat_id not in current_chat_ids:
                            current_chat_ids.add(chat_id)
                            await update_user(chat_id, username, chat_name)

                            if chat_id not in existing_chat_ids:
                                new_chats.append(chat_id)
                except (RPCError, InternalServerError) as exc:
                    if _is_fatal_session_error(exc):
                        await _drop_dead_session(app_session, exc)
                    else:
                        bot_logger.warning(f"get_dialogs error: {exc}")
                    continue

                bot_logger.info(
                    f"DIALOG SCAN USER: {user_id} | dialogs_count={total_dialogs} | "
                    f"parsed_unique={len(current_chat_ids)} | seen_total={len(seen_chat_ids)} | "
                    f"filtered_out={filtered_out_count}"
                )

                if not existing_chat_ids and current_chat_ids:
                    bot_logger.warning(
                        f"Baseline sync activated for user={user_id}: "
                        f"existing_dump_empty, bootstrap_size={len(current_chat_ids)}"
                    )
                    for chat_id in current_chat_ids:
                        await create_dump_chat_user(user_id, chat_id)

                    await update_account_uuid(
                        account_settings.uuid,
                        account_settings.admin_id,
                        last_update=now_ts,
                        last_dialogs_count=total_dialogs,
                        last_full_dialogs_scan=now_ts,
                        baseline_sync_done=1,
                        pending_delete_signature=None,
                        pending_delete_count=0,
                        pending_delete_since=None,
                    )
                    await add_account_health_event(
                        account_uuid=account_settings.uuid,
                        admin_id=account_settings.admin_id,
                        user_id=account_settings.user_id,
                        status=1,
                        date=now_ts,
                        reason="baseline_sync",
                    )
                    continue

                # Deletions are computed from all seen dialogs, not only filtered subset,
                # so toggling bot/channel filter doesn't create false "deleted" events.
                deleted_chats = existing_chat_ids - seen_chat_ids
                existing_count = len(existing_chat_ids)
                deleted_count = len(deleted_chats)
                deleted_ratio = (deleted_count / existing_count) if existing_count else 0.0
                is_mass_delete_candidate = (
                    existing_count >= MASS_DELETE_MIN_EXISTING
                    and deleted_count >= MASS_DELETE_MIN_COUNT
                    and deleted_ratio >= MASS_DELETE_MIN_RATIO
                )

                mass_delete_guard_triggered = False
                pending_delete_signature = None
                pending_delete_count = 0
                pending_delete_since = None

                if is_mass_delete_candidate:
                    signature = _ids_signature(deleted_chats)
                    prev_signature = getattr(account_settings, "pending_delete_signature", None)
                    prev_count = int(getattr(account_settings, "pending_delete_count", 0) or 0)
                    if prev_signature == signature and prev_count == deleted_count:
                        bot_logger.warning(
                            f"Mass delete confirmed for user={user_id}: "
                            f"deleted={deleted_count}/{existing_count} ({deleted_ratio:.2%})"
                        )
                    else:
                        mass_delete_guard_triggered = True
                        pending_delete_signature = signature
                        pending_delete_count = deleted_count
                        pending_delete_since = now_ts
                        bot_logger.warning(
                            f"Mass delete guard for user={user_id}: "
                            f"deleted={deleted_count}/{existing_count} ({deleted_ratio:.2%}), "
                            "waiting for next scan confirmation"
                        )
                        deleted_chats = set()
                all_changes = new_chats + list(deleted_chats)

                log_new = []
                log_del = []

                for chat_id in all_changes:
                    user = await get_user(chat_id)
                    username = user.username if user else constant_text.PARSER_UNKNOWN_ERROR_TEXT
                    chat_name = user.full_name if user else constant_text.PARSER_UNKNOWN_ERROR_TEXT
                    quote = html.quote(chat_name) if chat_name else chat_name

                    if chat_id in new_chats:
                        created = await create_dump_chat_user(user_id, chat_id)
                        if not created:
                            continue
                        bot_logger.info(constant_text.PARSER_LOG_NEW_CHAT_TEXT.format(user_id=user_id, chat_id=chat_id, username=username, chat_name=chat_name))
                        await add_chat_history_event(
                            admin_id=int(account_settings.admin_id or user_id),
                            chat_id=int(chat_id),
                            action_id=1,
                            account_user_id=int(account_settings.user_id or 0),
                            date=now_ts,
                        )
                        log_new.append(get_user_log_text(1, chat_id, username, quote))
                    else:
                        bot_logger.info(constant_text.PARSER_LOG_DELETED_CHAT_TEXT.format(user_id=user_id, chat_id=chat_id, username=username, chat_name=chat_name))
                        await del_dump_chat_user(user_id, chat_id)
                        await add_chat_history_event(
                            admin_id=int(account_settings.admin_id or user_id),
                            chat_id=int(chat_id),
                            action_id=2,
                            account_user_id=int(account_settings.user_id or 0),
                            date=now_ts,
                        )
                        log_del.append(get_user_log_text(2, chat_id, username, quote))

                await update_account_uuid(
                    account_settings.uuid,
                    account_settings.admin_id,
                    last_update=now_ts,
                    last_dialogs_count=total_dialogs,
                    last_full_dialogs_scan=now_ts,
                    baseline_sync_done=1,
                    pending_delete_signature=pending_delete_signature if mass_delete_guard_triggered else None,
                    pending_delete_count=pending_delete_count if mass_delete_guard_triggered else 0,
                    pending_delete_since=pending_delete_since if mass_delete_guard_triggered else None,
                )
                await add_account_health_event(
                    account_uuid=account_settings.uuid,
                    admin_id=account_settings.admin_id,
                    user_id=account_settings.user_id,
                    status=1,
                    date=now_ts,
                    reason="mass_delete_guard" if mass_delete_guard_triggered else "ok",
                )

                if account_settings.alert_new_chat:
                    target_id = (
                        account_settings.admin_id
                        if account_settings.alert_new_chat_id < 10
                        else account_settings.alert_new_chat_id
                    )
                    for text_chunk in chunk_text(log_new):
                        await bot.send_message(target_id, text_chunk)

                if account_settings.alert_del_chat:
                    target_id = (
                        account_settings.admin_id
                        if account_settings.alert_del_chat_id < 10
                        else account_settings.alert_del_chat_id
                    )
                    for text_chunk in chunk_text(log_del):
                        await bot.send_message(target_id, text_chunk)

            except Exception as exc:
                if account_settings is not None:
                    await add_account_health_event(
                        account_uuid=account_settings.uuid,
                        admin_id=account_settings.admin_id,
                        user_id=account_settings.user_id,
                        status=0,
                        date=DateTime().timestamp(),
                        reason=exc.__class__.__name__,
                    )

                if _is_fatal_session_error(exc):
                    await _drop_dead_session(app_session, exc)
                else:
                    bot_logger.error(traceback.format_exc())

    except Exception:
        bot_logger.error(traceback.format_exc())


async def starting_tg_parse_dialogs_handler() -> None:
    bot_logger.debug("starting tg_parse_dialogs_handler")
    await __tg_parse_dialogs_handler()
    scheduler.start()

