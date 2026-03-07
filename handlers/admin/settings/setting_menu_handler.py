from datetime import timedelta

from aiogram import F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import data.text as constant_text
from db.main import get_accounts_overview, get_admin_health_events, get_all_health_events
from filters.all_filters import IsAdmin, IsPrivate
from loader import router
from utils.datetime_tools import DateTime


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


def _build_hourly_rows_desc(events, hours: int) -> list[str]:
    dt = DateTime()
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


def _build_daily_rows_desc(events, days: int) -> list[str]:
    dt = DateTime()
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


def _recent_failures(events, limit: int = 5) -> str:
    failed = [x for x in events if int(x.status) == 0]
    failed.sort(key=lambda x: int(x.date), reverse=True)

    if not failed:
        return constant_text.STATS_RECENT_EMPTY

    rows = []
    for item in failed[:limit]:
        stamp = DateTime().convert_timestamp(int(item.date), "%d.%m %H:%M")["str"]
        reason = (item.reason or "error").strip()
        if len(reason) > 28:
            reason = reason[:28] + "..."
        rows.append(constant_text.STATS_RECENT_ROW.format(stamp=stamp, reason=reason))

    return "\n".join(rows)


async def _send_stats(message: Message, admin_only: bool) -> None:
    admin_id = message.from_user.id
    overview = await get_accounts_overview(admin_id)

    now_ts = DateTime().timestamp()
    since_24h = now_ts - 60 * 60 * 24
    since_14d = now_ts - 60 * 60 * 24 * 14

    if admin_only:
        events_24h = await get_admin_health_events(admin_id, since_24h)
        events_14d = await get_admin_health_events(admin_id, since_14d)
        title = constant_text.STATS_TITLE_OWN
    else:
        events_24h = await get_all_health_events(since_24h)
        events_14d = await get_all_health_events(since_14d)
        title = constant_text.STATS_TITLE_GLOBAL

    fail_24h = sum(1 for x in events_24h if int(x.status) == 0)
    fail_14d = sum(1 for x in events_14d if int(x.status) == 0)

    success_24h = _success_percent(events_24h)
    success_14d = _success_percent(events_14d)

    by_hour_text = "\n".join(_build_hourly_rows_desc(events_24h, hours=24))
    by_day_text = "\n".join(_build_daily_rows_desc(events_14d, days=14))

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
            recent_failures=_recent_failures(events_14d, limit=5),
        )
    )


@router.message(IsPrivate(), IsAdmin(), F.text == constant_text.SETTINGS_BOT_KEYBOARD[0], StateFilter("*"))
async def open_my_stats_handler(message: Message, state: FSMContext):
    await state.clear()
    await _send_stats(message, admin_only=True)


@router.message(IsPrivate(), IsAdmin(), F.text == constant_text.SETTINGS_BOT_KEYBOARD[1], StateFilter("*"))
async def open_global_stats_handler(message: Message, state: FSMContext):
    await state.clear()
    await _send_stats(message, admin_only=False)
