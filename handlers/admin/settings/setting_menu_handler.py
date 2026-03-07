import time
from datetime import timedelta

import aiohttp
from aiogram import F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

import data.text as constant_text
from core.process_control import restart_current_process
from core.session_runtime import stop_client
from core.versioning import get_local_version, get_remote_version_url, is_newer_version
from db.main import (
    get_accounts_overview,
    get_admin_health_events,
    get_all_health_events,
    get_user_auto_update_enabled,
    get_user_timezone_offset,
    set_user_auto_update_enabled,
    set_user_timezone_offset,
    set_user_update_snooze_until,
)
from filters.all_filters import IsAdmin, IsPrivate
from loader import apps_session, router
from utils.datetime_tools import DateTime
from utils.others import not_warning_delete_message

DEFAULT_TIMEZONE_OFFSET = 3
_VERSION_CACHE_TTL_SEC = 120
_VERSION_CACHE = {
    "checked_at": 0,
    "state": "неизвестно",
    "latest": None,
}


def _tz_label(offset: int) -> str:
    sign = "+" if int(offset) >= 0 else ""
    return f"{sign}{int(offset)}"


def _auto_update_label(enabled: int) -> str:
    return constant_text.AUTO_UPDATE_ON_TEXT if int(enabled) == 1 else constant_text.AUTO_UPDATE_OFF_TEXT


def _status_icon(fails: int, total: int) -> str:
    if total == 0:
        return constant_text.STATS_ICON_NO_DATA
    ratio = fails / total
    if ratio == 0:
        return constant_text.STATS_ICON_OK
    if ratio < 0.35:
        return constant_text.STATS_ICON_WARN
    return constant_text.STATS_ICON_FAIL


def _success_percent(events) -> float:
    if not events:
        return 0.0
    ok = sum(1 for x in events if int(x.status) == 1)
    return round((ok / len(events)) * 100, 2)


def _build_hourly_rows_desc(events, hours: int, dt: DateTime) -> list[str]:
    now_hour = dt.now().replace(minute=0, second=0, microsecond=0)
    rows: list[str] = []

    for i in range(hours):
        end_dt = now_hour - timedelta(hours=i)
        start_dt = end_dt - timedelta(hours=1)

        start_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp())

        bucket_events = [x for x in events if start_ts <= int(x.date) < end_ts]
        total = len(bucket_events)
        fails = sum(1 for x in bucket_events if int(x.status) == 0)
        pct = 0 if total == 0 else round(((total - fails) / total) * 100)

        end_label = end_dt.strftime("%H:00")
        start_label = start_dt.strftime("%H:00")
        rows.append(f"{end_label} - {_status_icon(fails, total)} - {pct}% - {start_label}")

    return rows


def _build_daily_rows_desc(events, days: int, dt: DateTime) -> list[str]:
    today_00 = dt.now().replace(hour=0, minute=0, second=0, microsecond=0)
    rows: list[str] = []

    for i in range(days):
        end_dt = today_00 - timedelta(days=i)
        start_dt = end_dt - timedelta(days=1)

        start_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp())

        bucket_events = [x for x in events if start_ts <= int(x.date) < end_ts]
        total = len(bucket_events)
        fails = sum(1 for x in bucket_events if int(x.status) == 0)
        pct = 0 if total == 0 else round(((total - fails) / total) * 100)

        end_label = end_dt.strftime("%d.%m 00:00")
        start_label = start_dt.strftime("%d.%m 00:00")
        rows.append(f"{end_label} - {_status_icon(fails, total)} - {pct}% - {start_label}")

    return rows


def _recent_failures(events, dt: DateTime, limit: int = 5) -> str:
    failed = [x for x in events if int(x.status) == 0]
    failed.sort(key=lambda x: int(x.date), reverse=True)

    if not failed:
        return constant_text.STATS_RECENT_EMPTY

    rows = []
    for item in failed[:limit]:
        stamp = dt.convert_timestamp(int(item.date), "%d.%m %H:%M")["str"]
        reason = (item.reason or "error").strip()
        if len(reason) > 28:
            reason = reason[:28] + "..."
        rows.append(constant_text.STATS_RECENT_ROW.format(stamp=stamp, reason=reason))

    return "\n".join(rows)


async def _fetch_latest_version() -> str | None:
    timeout = aiohttp.ClientTimeout(total=12)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(get_remote_version_url()) as response:
                if response.status != 200:
                    return None
                return (await response.text()).strip() or None
    except Exception:
        return None


async def _get_version_state(force: bool = False) -> tuple[str, int, str | None]:
    now_ts = int(time.time())
    checked_at = int(_VERSION_CACHE["checked_at"] or 0)

    if not force and checked_at > 0 and (now_ts - checked_at) < _VERSION_CACHE_TTL_SEC:
        return str(_VERSION_CACHE["state"]), checked_at, _VERSION_CACHE["latest"]

    local_version = get_local_version()
    latest_version = await _fetch_latest_version()

    if not latest_version:
        state = "неизвестно"
    elif is_newer_version(local_version, latest_version):
        state = f"доступна {latest_version}"
    else:
        state = "актуальная"

    _VERSION_CACHE["checked_at"] = now_ts
    _VERSION_CACHE["state"] = state
    _VERSION_CACHE["latest"] = latest_version

    return state, now_ts, latest_version


def _minutes_ago(ts_value: int) -> int:
    if ts_value <= 0:
        return 0
    return max(0, int((time.time() - ts_value) // 60))


async def _send_stats(message: Message, admin_only: bool) -> None:
    admin_id = message.from_user.id
    overview = await get_accounts_overview(admin_id)

    tz_offset = await get_user_timezone_offset(admin_id)
    dt = DateTime(tz_offset)

    now_ts = int(time.time())
    since_24h = now_ts - 60 * 60 * 24
    since_14d = now_ts - 60 * 60 * 24 * 14

    if admin_only:
        events_24h = await get_admin_health_events(admin_id, since_24h)
        events_14d = await get_admin_health_events(admin_id, since_14d)
        title = f"{constant_text.STATS_TITLE_OWN} (+{_tz_label(tz_offset).lstrip('+')})"
    else:
        events_24h = await get_all_health_events(since_24h)
        events_14d = await get_all_health_events(since_14d)
        title = f"{constant_text.STATS_TITLE_GLOBAL} (+{_tz_label(tz_offset).lstrip('+')})"

    fail_24h = sum(1 for x in events_24h if int(x.status) == 0)
    fail_14d = sum(1 for x in events_14d if int(x.status) == 0)

    success_24h = _success_percent(events_24h)
    success_14d = _success_percent(events_14d)

    by_hour_text = "\n".join(_build_hourly_rows_desc(events_24h, hours=24, dt=dt))
    by_day_text = "\n".join(_build_daily_rows_desc(events_14d, days=14, dt=dt))

    await message.answer(
        constant_text.STATS_TEXT.format(
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
            recent_failures=_recent_failures(events_14d, dt=dt, limit=5),
        )
    )


async def _settings_text(admin_id: int) -> str:
    tz_offset = await get_user_timezone_offset(admin_id)
    auto_update = await get_user_auto_update_enabled(admin_id)
    version_state, checked_at, _ = await _get_version_state(force=False)

    return constant_text.SETTINGS_MENU_TITLE.format(
        bot_version=get_local_version(),
        version_state=version_state,
        last_check_ago=_minutes_ago(checked_at),
        date=DateTime(tz_offset).time_strftime("%d.%m.%Y %H:%M:%S.%f"),
        auto_update_state=_auto_update_label(auto_update),
    )


async def _settings_inline(admin_id: int):
    tz_offset = await get_user_timezone_offset(admin_id)
    auto_update = await get_user_auto_update_enabled(admin_id)

    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.SETTINGS_BTN_AUTO_UPDATE.format(state=_auto_update_label(auto_update)),
            callback_data=f"set:au:{0 if auto_update else 1}",
        ),
    )
    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.SETTINGS_BTN_CHECK_UPDATE,
            callback_data="set:update:check",
        ),
    )
    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.SETTINGS_BTN_TIMEZONE.format(tz_label=_tz_label(tz_offset)),
            callback_data="set:tz:open",
        )
    )
    keyboard.row(
        InlineKeyboardButton(text=constant_text.SETTINGS_BTN_RESTART, callback_data="set:reboot"),
    )
    keyboard.row(
        InlineKeyboardButton(text=constant_text.SETTINGS_BTN_CLOSE, callback_data="set:close"),
    )
    return keyboard.as_markup()


def _timezone_inline(current_offset: int):
    keyboard = InlineKeyboardBuilder()
    offsets = list(range(-12, 15))

    for i in range(0, len(offsets), 3):
        buttons = []
        for value in offsets[i : i + 3]:
            base_text = constant_text.TIMEZONE_BTN_PREFIX.format(
                offset=(f"+{value}" if value >= 0 else str(value))
            )
            text = (
                constant_text.TIMEZONE_BTN_SELECTED.format(label=base_text)
                if value == current_offset
                else base_text
            )
            buttons.append(InlineKeyboardButton(text=text, callback_data=f"set:tz:{value}"))
        keyboard.row(*buttons)

    keyboard.row(InlineKeyboardButton(text=constant_text.TIMEZONE_BTN_RESET, callback_data="set:tz:reset"))
    keyboard.row(InlineKeyboardButton(text=constant_text.ACTION_BACK_TEXT, callback_data="set:back"))
    return keyboard.as_markup()


async def _safe_edit_settings(call: CallbackQuery) -> None:
    text = await _settings_text(call.from_user.id)
    markup = await _settings_inline(call.from_user.id)
    try:
        await call.message.edit_text(text=text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


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
    await not_warning_delete_message(message=call)
    await call.answer(constant_text.ACTION_CANCELLED_TEXT)


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "set:update:check", StateFilter("*"))
async def check_update_now_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    local_version = get_local_version()
    version_state, _, latest_version = await _get_version_state(force=True)

    if latest_version and is_newer_version(local_version, latest_version):
        await call.answer(constant_text.SETTINGS_UPDATE_AVAILABLE_TOAST.format(latest_version=latest_version))
    elif version_state == "неизвестно":
        await call.answer(constant_text.SETTINGS_UPDATE_UNKNOWN_TOAST)
    else:
        await call.answer(constant_text.SETTINGS_UPDATE_OK_TOAST)

    await _safe_edit_settings(call)


@router.callback_query(IsPrivate(), IsAdmin(), F.data.startswith("set:au:"), StateFilter("*"))
async def set_auto_update_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    try:
        value = int(call.data.split(":")[-1])
    except Exception:
        return await call.answer(constant_text.ERROR_FORMAT_TEXT)

    await set_user_auto_update_enabled(call.from_user.id, value)
    await call.answer(constant_text.SETTINGS_TOAST_UPDATED)
    await _safe_edit_settings(call)


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "set:tz:open", StateFilter("*"))
async def open_timezone_menu_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()
    current_offset = await get_user_timezone_offset(call.from_user.id)

    await call.message.edit_text(
        constant_text.TIMEZONE_MENU_TEXT.format(tz_label=_tz_label(current_offset)),
        reply_markup=_timezone_inline(current_offset),
    )


@router.callback_query(IsPrivate(), IsAdmin(), F.data.startswith("set:tz:"), StateFilter("*"))
async def set_timezone_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    if call.data == "set:tz:open":
        return

    if call.data == "set:tz:reset":
        saved = await set_user_timezone_offset(call.from_user.id, DEFAULT_TIMEZONE_OFFSET)
        await call.answer(constant_text.TIMEZONE_RESET_TOAST)
        return await call.message.edit_text(
            constant_text.TIMEZONE_MENU_TEXT.format(tz_label=_tz_label(saved)),
            reply_markup=_timezone_inline(saved),
        )

    try:
        offset = int(call.data.split(":")[-1])
    except Exception:
        return await call.answer(constant_text.TIMEZONE_INVALID_TOAST)

    if offset < -12 or offset > 14:
        return await call.answer(constant_text.TIMEZONE_INVALID_TOAST)

    saved = await set_user_timezone_offset(call.from_user.id, offset)
    await call.answer(constant_text.TIMEZONE_SET_TOAST.format(tz_label=_tz_label(saved)))

    await call.message.edit_text(
        constant_text.TIMEZONE_MENU_TEXT.format(tz_label=_tz_label(saved)),
        reply_markup=_timezone_inline(saved),
    )


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "set:back", StateFilter("*"))
async def back_to_settings_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await _safe_edit_settings(call)


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "set:reboot", StateFilter("*"))
async def reboot_from_settings_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    await call.message.edit_text(constant_text.RESTARTING_TEXT)
    for app in list(apps_session):
        await stop_client(app)

    restart_current_process()


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "upd:close", StateFilter("*"))
async def update_notice_close_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await not_warning_delete_message(message=call)
    await call.answer(constant_text.UPDATE_NOTIFY_CLOSED_TOAST)


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "upd:snooze", StateFilter("*"))
async def update_notice_snooze_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    until_ts = int(time.time()) + 60 * 60 * 24 * 7
    await set_user_update_snooze_until(call.from_user.id, until_ts)

    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.UPDATE_NOTIFY_BTN_CLOSE,
            callback_data="upd:close",
        )
    )

    await call.message.edit_reply_markup(reply_markup=keyboard.as_markup())
    await call.answer(constant_text.UPDATE_NOTIFY_SNOOZE_TOAST)
