from __future__ import annotations

import asyncio
import time
from typing import Iterable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import data.text as constant_text
from core.async_tools import create_logged_task, tracked_job
from core.thread_tools import run_blocking
from core.logging import bot_logger
from core.process_control import restart_with_clients
from core.versioning import fetch_remote_version, get_local_version, get_remote_version_url, is_newer_version
from db.main import (
    get_admin_ids,
    get_user_auto_update_enabled,
    get_user_update_notification_state,
    set_user_update_last_notified,
    set_version_state_cache,
)
from loader import bot
from scripts.update_bot import download_and_extract_github_repo
from scripts.startup_status import begin_operation
from services.startup_notifications import announce_update
from keyboards.inline.settings import update_notification_keyboard as _notification_keyboard

NOTIFY_INTERVAL_SEC = 60 * 60 * 24

update_scheduler = AsyncIOScheduler()
_update_lock = asyncio.Lock()
_update_run_lock = asyncio.Lock()
_update_running = False



async def _collect_admin_ids() -> list[int]:
    return sorted(user_id for user_id in await get_admin_ids() if user_id > 10)


async def _safe_send(
    chat_id: int,
    text: str,
    include_snooze: bool = True,
    include_update: bool = False,
    include_close: bool = True,
) -> bool:
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=_notification_keyboard(
                include_snooze=include_snooze,
                include_update=include_update,
                include_close=include_close,
            ),
        )
        return True
    except Exception as exc:
        bot_logger.warning(f"Cannot send update notification to {chat_id}: {exc}")
        return False


async def _restart_process() -> None:
    await restart_with_clients()


async def try_acquire_update_run() -> bool:
    global _update_running
    async with _update_run_lock:
        if _update_running:
            return False
        _update_running = True
        return True


async def release_update_run() -> None:
    global _update_running
    async with _update_run_lock:
        _update_running = False


async def _run_auto_update(target_ids: Iterable[int], current_version: str, latest_version: str) -> None:
    ids = list({int(x) for x in target_ids if int(x) > 10})
    if not ids:
        return
    if not await try_acquire_update_run():
        bot_logger.info("Skip auto update: another update flow already running")
        return

    reporter = begin_operation("Обновление", recipients=ids)
    try:
        start_text = constant_text.AUTO_UPDATE_START_TEXT.format(
            from_version=current_version,
            to_version=latest_version,
        )
        if reporter is not None:
            await announce_update(bot, reporter, current_version, latest_version)
            reporter.update("Загрузка обновления", f"Версия {current_version} → {latest_version}")
        else:
            for admin_id in ids:
                await _safe_send(admin_id, start_text, include_snooze=False, include_close=False)

        options = {"expected_version": latest_version}
        if reporter is not None:
            options["progress"] = reporter.update
        ok = await run_blocking(download_and_extract_github_repo, **options)

        if not ok:
            if reporter is not None:
                reporter.finish(success=False, detail="Не удалось загрузить обновление. Бот продолжает работать на текущем коде; проверьте локальные логи.")
                return
            for admin_id in ids:
                await _safe_send(
                    admin_id,
                    constant_text.AUTO_UPDATE_FAILED_TEXT,
                    include_snooze=False,
                    include_close=False,
                )
            return

        done_text = constant_text.AUTO_UPDATE_DONE_TEXT.format(to_version=latest_version)
        if reporter is not None:
            reporter.update("Обновление загружено", "Подготовка к перезапуску и проверке зависимостей")
        else:
            for admin_id in ids:
                await _safe_send(admin_id, done_text, include_snooze=False, include_close=False)

        await asyncio.sleep(2)
        await _restart_process()
    except BaseException as error:
        if reporter is not None:
            reporter.fail(error)
        raise
    finally:
        await release_update_run()


@update_scheduler.scheduled_job("interval", minutes=30)
@tracked_job
async def version_check_job() -> None:
    async with _update_lock:
        current_version = get_local_version()
        latest_version = await fetch_remote_version(timeout_sec=15, log_prefix="Notifier version check")
        now_ts = int(time.time())

        bot_logger.debug(
            f"Notifier version check: local={current_version} remote={latest_version or 'n/a'} "
            f"url={get_remote_version_url()}"
        )

        if not latest_version:
            await set_version_state_cache(
                local_version=current_version,
                remote_version=None,
                state=constant_text.VERSION_STATE_UNKNOWN,
                checked_at=now_ts,
            )
            return

        if is_newer_version(current_version, latest_version):
            state_text = constant_text.VERSION_STATE_UPDATE_AVAILABLE.format(latest_version=latest_version)
        else:
            state_text = constant_text.VERSION_STATE_UP_TO_DATE

        await set_version_state_cache(
            local_version=current_version,
            remote_version=latest_version,
            state=state_text,
            checked_at=now_ts,
        )

        if not is_newer_version(current_version, latest_version):
            return

        notify_text = constant_text.UPDATE_NOTIFY_TEXT.format(
            current_version=current_version,
            latest_version=latest_version,
        )

        admin_ids = await _collect_admin_ids()
        auto_update_targets: list[int] = []

        for admin_id in admin_ids:
            snooze_until, last_notified = await get_user_update_notification_state(admin_id)
            auto_update_enabled = await get_user_auto_update_enabled(admin_id)

            if auto_update_enabled == 1:
                auto_update_targets.append(admin_id)
                continue

            if now_ts < int(snooze_until):
                continue

            if (now_ts - int(last_notified)) < NOTIFY_INTERVAL_SEC:
                continue

            sent = await _safe_send(
                admin_id,
                notify_text,
                include_snooze=True,
                include_update=True,
            )
            if sent:
                await set_user_update_last_notified(admin_id, now_ts)

        if auto_update_targets:
            await _run_auto_update(auto_update_targets, current_version, latest_version)


async def start_update_notifier() -> None:
    if update_scheduler.running:
        return

    bot_logger.info("Starting update notifier scheduler")
    update_scheduler.start()
    create_logged_task(version_check_job(), name="update_notifier_initial_check")

