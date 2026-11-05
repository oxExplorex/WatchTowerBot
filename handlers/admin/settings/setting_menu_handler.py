import asyncio
import time

from aiogram import F, Router, html
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import data.text as constant_text
from data.config import GEMINI_KEY
from core.logging import bot_logger
from core.thread_tools import run_blocking
from core.process_control import restart_with_clients
from core.versioning import fetch_remote_version, get_local_version, get_remote_version_url, is_newer_version
from db.main import (
    disable_user_gemini_proxy,
    get_accounts_overview,
    get_admin_health_events,
    get_all_health_events,
    get_latest_admin_health_event,
    get_user_auto_update_enabled,
    get_user_gemini_proxy_config,
    get_user_timezone_offset,
    get_version_state_cache,
    set_user_auto_update_enabled,
    set_user_gemini_proxy_health,
    set_user_timezone_offset,
    set_user_update_snooze_until,
    set_version_state_cache,
)
from filters.all_filters import IsAdmin, IsPrivate
from aiotask.update_notifier import release_update_run, try_acquire_update_run
from handlers.admin.proxy_manager.proxy_checker import check_proxy_now
from utils.settings_formatting import (
    auto_update_label,
    build_daily_rows_desc,
    build_hourly_rows_desc,
    gemini_runtime_label,
    minutes_ago,
    parser_runtime_label,
    proxy_status_label,
    recent_failures,
    success_percent,
    timezone_rows_text,
    tz_full_label,
    tz_offset_label,
)

from scripts.update_bot import download_and_extract_github_repo
from scripts.startup_status import begin_operation
from utils.datetime_tools import DateTime
from utils.others import not_warning_delete_message
from utils.proxy_utils import compact_proxy_display, normalize_http_proxy_input

from keyboards.inline.settings import settings_keyboard, timezone_keyboard, update_notice_close_keyboard
from keyboards.inline.navigation import navigation_keyboard
from utils.panel import edit_panel
from keyboards.main.start_keyboard import static_admin_keyboard

router = Router(name=__name__)

DEFAULT_TIMEZONE_OFFSET = 3


async def _fetch_latest_version() -> str | None:
    return await fetch_remote_version(timeout_sec=12, log_prefix="Settings version check")


async def _get_version_state(force: bool = False) -> tuple[str, int, str | None]:
    if not force:
        return await get_version_state_cache(default_state=constant_text.VERSION_STATE_UNKNOWN)

    local_version = get_local_version()
    latest_version = await _fetch_latest_version()

    if not latest_version:
        state = constant_text.VERSION_STATE_UNKNOWN
    elif is_newer_version(local_version, latest_version):
        state = constant_text.VERSION_STATE_UPDATE_AVAILABLE.format(latest_version=latest_version)
    else:
        state = constant_text.VERSION_STATE_UP_TO_DATE

    checked_at = await set_version_state_cache(
        local_version=local_version,
        remote_version=latest_version,
        state=state,
    )
    return state, checked_at, latest_version


async def _get_cached_version_state() -> tuple[str, int, str | None]:
    return await get_version_state_cache(default_state=constant_text.VERSION_STATE_UNKNOWN)


async def _send_stats(message: Message, admin_only: bool, *, admin_id=None, edit=False) -> None:
    admin_id = message.from_user.id if admin_id is None else admin_id
    overview = await get_accounts_overview(admin_id)

    tz_offset = await get_user_timezone_offset(admin_id)
    dt = DateTime(tz_offset)

    now_ts = int(time.time())
    since_24h = now_ts - 60 * 60 * 24
    since_14d = now_ts - 60 * 60 * 24 * 14

    if admin_only:
        events_24h = await get_admin_health_events(admin_id, since_24h)
        events_14d = await get_admin_health_events(admin_id, since_14d)
        title = f"{constant_text.STATS_TITLE_OWN} ({tz_offset_label(tz_offset)})"
    else:
        events_24h = await get_all_health_events(since_24h)
        events_14d = await get_all_health_events(since_14d)
        title = f"{constant_text.STATS_TITLE_GLOBAL} ({tz_offset_label(tz_offset)})"

    fail_24h = sum(1 for x in events_24h if int(x.status) == 0)
    fail_14d = sum(1 for x in events_14d if int(x.status) == 0)

    success_24h = success_percent(events_24h)
    success_14d = success_percent(events_14d)

    by_hour_text = "\n".join(build_hourly_rows_desc(events_24h, hours=24, dt=dt))
    by_day_text = "\n".join(build_daily_rows_desc(events_14d, days=14, dt=dt))

    content = constant_text.STATS_TEXT.format(
            title=title,
            own_active=overview["own_active"],
            own_total=overview["own_total"],
            all_active=overview["all_active"],
            all_total=overview["all_total"],
            success_24h=success_24h,
            fail_24h=fail_24h,
            success_14d=success_14d,
            fail_14d=fail_14d,
            by_hour_text=by_hour_text,
            by_day_text=by_day_text,
            recent_failures=recent_failures(events_14d, dt=dt, limit=5),
        )
    if edit:
        await edit_panel(message, content, navigation_keyboard())
    else:
        await message.answer(content, reply_markup=navigation_keyboard())


async def _settings_text(admin_id: int) -> str:
    tz_offset = await get_user_timezone_offset(admin_id)
    version_state, checked_at, _ = await _get_cached_version_state()

    now_ts = int(time.time())
    last_event = await get_latest_admin_health_event(admin_id)
    proxy_cfg = await get_user_gemini_proxy_config(admin_id)

    parser_status = parser_runtime_label(last_event, now_ts)
    gemini_status = gemini_runtime_label(proxy_cfg, key_available=bool(GEMINI_KEY))
    proxy_status = proxy_status_label(proxy_cfg)
    proxy = proxy_cfg.get("proxy")
    proxy_details = (constant_text.SETTINGS_PROXY_ADDRESS_TEXT.format(
        proxy=html.quote(compact_proxy_display(proxy)),
    ) if proxy else "")
    check_age = minutes_ago(checked_at)
    if checked_at <= 0:
        last_check = constant_text.SETTINGS_CHECK_NEVER_TEXT
    elif check_age == 0:
        last_check = constant_text.SETTINGS_CHECK_JUST_NOW_TEXT
    else:
        last_check = constant_text.SETTINGS_CHECK_AGO_TEXT.format(minutes=check_age)

    return constant_text.SETTINGS_MENU_TITLE.format(
        bot_version=html.quote(get_local_version()),
        version_state=html.quote(version_state),
        last_check=last_check,
        parser_status=parser_status,
        gemini_status=gemini_status,
        proxy_status=proxy_status,
        proxy_details=proxy_details,
        date=DateTime(tz_offset).time_strftime("%d.%m.%Y %H:%M"),
        tz_label=tz_offset_label(tz_offset),
    )


async def _settings_inline(admin_id: int):
    tz_offset = await get_user_timezone_offset(admin_id)
    auto_update = await get_user_auto_update_enabled(admin_id)
    proxy_cfg = await get_user_gemini_proxy_config(admin_id)

    local_version = get_local_version()
    _, _, latest_version = await _get_cached_version_state()
    has_update = bool(latest_version and is_newer_version(local_version, latest_version))

    return settings_keyboard(tz_offset, auto_update, proxy_cfg, has_update)


async def _safe_edit_settings(call: CallbackQuery, notice=None) -> None:
    text = await _settings_text(call.from_user.id)
    if notice:
        text = f"{notice}\n\n{text}"
    markup = await _settings_inline(call.from_user.id)
    await edit_panel(call.message, text=text, reply_markup=markup)


async def _run_update_flow(
    message: Message,
    local_version: str,
    latest_version: str,
    start_text: str,
    done_text: str,
    failed_text: str,
) -> None:
    if not await try_acquire_update_run():
        await message.answer(constant_text.SETTINGS_UPDATE_RUNNING_TOAST)
        return

    reporter = begin_operation("Обновление", message=message)
    try:
        if reporter is not None:
            reporter.update("Загрузка обновления", f"Версия {local_version} → {latest_version}")
        else:
            await message.edit_text(start_text.format(from_version=local_version, to_version=latest_version))
        ok = await run_blocking(download_and_extract_github_repo)
        if not ok:
            if reporter is not None:
                reporter.finish(success=False, detail="Не удалось загрузить обновление. Бот продолжает работу; проверьте локальные логи.")
            else:
                await message.answer(failed_text)
            return

        if reporter is not None:
            reporter.update("Обновление загружено", "Подготовка к перезапуску и проверке зависимостей")
        else:
            await message.answer(done_text.format(to_version=latest_version))
        await asyncio.sleep(2)
        await restart_with_clients()
    except BaseException as error:
        if reporter is not None:
            reporter.fail(error)
        raise
    finally:
        await release_update_run()


@router.message(IsPrivate(), IsAdmin(), F.text == constant_text.SETTINGS_BOT_KEYBOARD[0], StateFilter("*"))
async def open_my_stats_handler(message: Message, state: FSMContext):
    await state.clear()
    await _send_stats(message, admin_only=True)


@router.message(IsPrivate(), IsAdmin(), F.text == constant_text.SETTINGS_BOT_KEYBOARD[1], StateFilter("*"))
async def open_global_stats_handler(message: Message, state: FSMContext):
    await state.clear()
    await _send_stats(message, admin_only=False)


@router.message(IsPrivate(), IsAdmin(), F.text == constant_text.SETTINGS_BOT_KEYBOARD[2], StateFilter("*"))
async def open_settings_menu_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        await _settings_text(message.from_user.id),
        reply_markup=await _settings_inline(message.from_user.id),
    )


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "set:close", StateFilter("*"))
async def close_settings_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit_panel(call.message, constant_text.START_MESSAGE_TEXT, static_admin_keyboard())
    await call.answer(constant_text.ACTION_CANCELLED_TEXT)


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "set:update:check", StateFilter("*"))
async def check_update_now_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    local_version = get_local_version()
    _, _, latest_version = await _get_version_state(force=True)

    bot_logger.info(
        f"Manual version check: local={local_version} remote={latest_version or 'n/a'} "
        f"url={get_remote_version_url()}"
    )

    if latest_version and is_newer_version(local_version, latest_version):
        await call.answer(
            constant_text.SETTINGS_UPDATE_AVAILABLE_TOAST.format(latest_version=latest_version)
        )
    elif not latest_version:
        await call.answer(constant_text.SETTINGS_UPDATE_UNKNOWN_TOAST)
    else:
        await call.answer(constant_text.SETTINGS_UPDATE_OK_TOAST)

    await _safe_edit_settings(call)


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "set:update:run", StateFilter("*"))
async def run_update_now_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    local_version = get_local_version()
    _, _, latest_version = await _get_version_state(force=True)

    if not latest_version:
        await call.answer(constant_text.SETTINGS_UPDATE_UNKNOWN_TOAST)
        return await _safe_edit_settings(call)

    if not is_newer_version(local_version, latest_version):
        await call.answer(constant_text.SETTINGS_UPDATE_ALREADY_LATEST_TOAST)
        return await _safe_edit_settings(call)

    await call.answer(constant_text.SETTINGS_UPDATE_RUNNING_TOAST)

    await _run_update_flow(
        message=call.message,
        local_version=local_version,
        latest_version=latest_version,
        start_text=constant_text.MANUAL_UPDATE_START_TEXT,
        done_text=constant_text.MANUAL_UPDATE_DONE_TEXT,
        failed_text=constant_text.MANUAL_UPDATE_FAILED_TEXT,
    )


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "set:proxy:check", StateFilter("*"))
async def check_proxy_from_settings_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer(constant_text.PROXY_CHECKING_TEXT)

    cfg = await get_user_gemini_proxy_config(call.from_user.id)
    proxy = cfg.get("proxy")
    enabled = int(cfg.get("enabled", 0) or 0)

    if not enabled or not proxy:
        await _safe_edit_settings(call, constant_text.PROXY_CHECK_SKIPPED_NO_PROXY_TEXT)
        return

    proxy_url = normalize_http_proxy_input(str(proxy))
    if not proxy_url:
        await set_user_gemini_proxy_health(call.from_user.id, is_ok=False, error="invalid_proxy_format")
        await _safe_edit_settings(call, constant_text.PROXY_INVALID_FORMAT_TEXT)
        return

    ok, reason = await check_proxy_now(call.from_user.id, proxy_url, log_source="setting_menu_handler")
    if ok:
        notice = constant_text.PROXY_CHECK_OK_TEXT
    else:
        notice = constant_text.PROXY_CHECK_FAIL_TEXT.format(reason=html.quote(reason[:160]))
    await _safe_edit_settings(call, notice)


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "set:proxy:disable", StateFilter("*"))
async def disable_proxy_from_settings_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await disable_user_gemini_proxy(call.from_user.id, reason="manual_disable")
    await call.answer(constant_text.PROXY_DISABLED_TEXT)
    await _safe_edit_settings(call)


@router.callback_query(IsPrivate(), IsAdmin(), F.data.startswith("set:au:"), StateFilter("*"))
async def set_auto_update_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    try:
        value = int(call.data.split(":")[-1])
    except (TypeError, ValueError, IndexError):
        return await call.answer(constant_text.ERROR_FORMAT_TEXT)

    await set_user_auto_update_enabled(call.from_user.id, value)
    await call.answer(constant_text.SETTINGS_TOAST_UPDATED)
    await _safe_edit_settings(call)


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "set:tz:open", StateFilter("*"))
async def open_timezone_menu_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    current_offset = await get_user_timezone_offset(call.from_user.id)

    await edit_panel(call.message,
        constant_text.TIMEZONE_MENU_TEXT.format(
            tz_label=tz_full_label(current_offset),
            tz_rows=timezone_rows_text(),
        ),
        reply_markup=timezone_keyboard(current_offset),
    )


@router.callback_query(IsPrivate(), IsAdmin(), F.data.startswith("set:tz:"), StateFilter("*"))
async def set_timezone_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    if call.data == "set:tz:open":
        return

    if call.data == "set:tz:reset":
        saved = await set_user_timezone_offset(call.from_user.id, DEFAULT_TIMEZONE_OFFSET)
        await call.answer(constant_text.TIMEZONE_RESET_TOAST)
        return await edit_panel(call.message,
            constant_text.TIMEZONE_MENU_TEXT.format(
                tz_label=tz_full_label(saved),
                tz_rows=timezone_rows_text(),
            ),
            reply_markup=timezone_keyboard(saved),
        )

    try:
        offset = int(call.data.split(":")[-1])
    except (TypeError, ValueError, IndexError):
        return await call.answer(constant_text.TIMEZONE_INVALID_TOAST)

    if offset < -12 or offset > 14:
        return await call.answer(constant_text.TIMEZONE_INVALID_TOAST)

    saved = await set_user_timezone_offset(call.from_user.id, offset)
    await call.answer(constant_text.TIMEZONE_SET_TOAST.format(tz_label=tz_full_label(saved)))

    await edit_panel(call.message,
        constant_text.TIMEZONE_MENU_TEXT.format(
            tz_label=tz_full_label(saved),
            tz_rows=timezone_rows_text(),
        ),
        reply_markup=timezone_keyboard(saved),
    )


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "set:back", StateFilter("*"))
@router.callback_query(IsPrivate(), IsAdmin(), F.data == "panel:settings", StateFilter("*"))
async def back_to_settings_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await _safe_edit_settings(call)
    await call.answer()


@router.callback_query(IsPrivate(), IsAdmin(), F.data.in_({"panel:stats:own", "panel:stats:all"}), StateFilter("*"))
async def open_stats_callback(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await _send_stats(call.message, admin_only=call.data.endswith(":own"), admin_id=call.from_user.id, edit=True)
    await call.answer()


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "set:reboot", StateFilter("*"))
async def reboot_from_settings_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    await call.message.edit_text(constant_text.RESTARTING_TEXT)
    await restart_with_clients()


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "upd:close", StateFilter("*"))
async def update_notice_close_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await not_warning_delete_message(message=call)
    await call.answer(constant_text.UPDATE_NOTIFY_CLOSED_TOAST)

@router.callback_query(IsPrivate(), IsAdmin(), F.data == "upd:update", StateFilter("*"))
async def update_notice_run_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    local_version = get_local_version()
    _, _, latest_version = await _get_version_state(force=True)

    if not latest_version:
        return await call.answer(constant_text.SETTINGS_UPDATE_UNKNOWN_TOAST)

    if not is_newer_version(local_version, latest_version):
        return await call.answer(constant_text.SETTINGS_UPDATE_ALREADY_LATEST_TOAST)

    await call.answer(constant_text.SETTINGS_UPDATE_RUNNING_TOAST)

    await _run_update_flow(
        message=call.message,
        local_version=local_version,
        latest_version=latest_version,
        start_text=constant_text.MANUAL_UPDATE_START_TEXT,
        done_text=constant_text.MANUAL_UPDATE_DONE_TEXT,
        failed_text=constant_text.MANUAL_UPDATE_FAILED_TEXT,
    )


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "upd:snooze", StateFilter("*"))
async def update_notice_snooze_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    until_ts = int(time.time()) + 60 * 60 * 24 * 7
    await set_user_update_snooze_until(call.from_user.id, until_ts)

    await call.message.edit_reply_markup(reply_markup=update_notice_close_keyboard())
    await call.answer(constant_text.UPDATE_NOTIFY_SNOOZE_TOAST)


