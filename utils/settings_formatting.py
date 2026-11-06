from __future__ import annotations

import time
from html import escape
from datetime import timedelta

import data.text as constant_text
from data.texts.runtime_status import SESSION_ERRORS, STARTUP_FAILED
from utils.datetime_tools import DateTime


def format_archive_bytes(value):
    size = max(0, int(value))
    units = constant_text.STATS_SIZE_UNITS
    for unit in units[:-1]:
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == units[0] else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} {units[-1]}"


def tz_offset_label(offset: int) -> str:
    sign = "+" if int(offset) >= 0 else ""
    return f"{sign}{int(offset)}"


def tz_full_label(offset: int) -> str:
    value = int(offset)
    sign = "+" if value >= 0 else ""
    city = constant_text.TIMEZONE_LABELS.get(value)
    if city:
        return f"{sign}{value} {city}"
    return f"{sign}{value}"


def timezone_rows_text() -> str:
    rows: list[str] = []
    for offset in range(-12, 15):
        sign = "+" if offset >= 0 else ""
        city = constant_text.TIMEZONE_LABELS.get(offset, "")
        rows.append(f"{sign}{offset} {city}".strip())
    return "\n".join(rows)


def auto_update_label(enabled: int) -> str:
    return constant_text.AUTO_UPDATE_ON_TEXT if int(enabled) == 1 else constant_text.AUTO_UPDATE_OFF_TEXT


def parser_runtime_label(last_event, now_ts: int) -> str:
    if not last_event:
        return constant_text.SETTINGS_STATUS_NO_DATA_TEXT

    event_ts = int(getattr(last_event, "date", 0) or 0)
    event_status = int(getattr(last_event, "status", 0) or 0)
    age_sec = max(0, now_ts - event_ts)

    if event_status == 1 and age_sec <= 60 * 40:
        return constant_text.SETTINGS_PARSER_STATUS_OK_TEXT
    if event_status == 1:
        return constant_text.SETTINGS_PARSER_STATUS_STALE_TEXT
    return constant_text.SETTINGS_PARSER_STATUS_ERROR_TEXT


def gemini_runtime_label(proxy_cfg: dict, *, key_available: bool) -> str:
    if not key_available:
        return constant_text.SETTINGS_GEMINI_STATUS_KEY_MISSING_TEXT

    enabled = int(proxy_cfg.get("enabled", 0) or 0)
    status = int(proxy_cfg.get("status", 0) or 0)
    proxy = (proxy_cfg.get("proxy") or "").strip()

    if not enabled or not proxy:
        return constant_text.SETTINGS_GEMINI_STATUS_PROXY_MISSING_TEXT
    if status == 1:
        return constant_text.SETTINGS_GEMINI_STATUS_OK_TEXT

    last_error = (proxy_cfg.get("last_error") or "").strip()
    if last_error:
        return constant_text.SETTINGS_GEMINI_STATUS_PROXY_ERROR_TEXT
    return constant_text.SETTINGS_GEMINI_STATUS_PENDING_TEXT


def proxy_status_label(proxy_cfg: dict) -> str:
    enabled = int(proxy_cfg.get("enabled", 0) or 0)
    status = int(proxy_cfg.get("status", 0) or 0)
    checked_at = int(proxy_cfg.get("checked_at", 0) or 0)
    last_error = (proxy_cfg.get("last_error") or "").strip()

    if not enabled:
        return constant_text.SETTINGS_PROXY_STATE_OFF_TEXT
    if status == 1:
        return constant_text.SETTINGS_PROXY_STATE_OK_TEXT
    if checked_at > 0 and not last_error:
        return constant_text.SETTINGS_PROXY_STATE_OK_TEXT
    return constant_text.SETTINGS_PROXY_STATE_PENDING_TEXT


def status_icon(fails: int, total: int) -> str:
    if total == 0:
        return constant_text.STATS_ICON_NO_DATA
    ratio = fails / total
    if ratio == 0:
        return constant_text.STATS_ICON_OK
    if ratio < 0.35:
        return constant_text.STATS_ICON_WARN
    return constant_text.STATS_ICON_FAIL


def session_error_label(reason):
    reason = (reason or "error").strip()
    if reason.startswith("startup:"):
        code = reason.removeprefix("startup:")
        return STARTUP_FAILED.format(reason=SESSION_ERRORS.get(code, code))
    return SESSION_ERRORS.get(reason, reason)


def build_hourly_rows_desc(events, hours: int, dt: DateTime, *, label_format: str = "%H:00") -> list[str]:
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
        result = (constant_text.STATS_NO_CHECKS if total == 0 else constant_text.STATS_CHECK_RESULT.format(
            percent=round(((total - fails) / total) * 100), count=total))

        end_label = end_dt.strftime(label_format)
        start_label = start_dt.strftime(label_format)
        rows.append(f"{start_label} → {end_label} · {status_icon(fails, total)} {result}")

    return rows


def build_daily_rows_desc(events, days: int, dt: DateTime) -> list[str]:
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
        result = (constant_text.STATS_NO_CHECKS if total == 0 else constant_text.STATS_CHECK_RESULT.format(
            percent=round(((total - fails) / total) * 100), count=total))

        end_label = end_dt.strftime("%d.%m 00:00")
        start_label = start_dt.strftime("%d.%m 00:00")
        rows.append(f"{start_label} → {end_label} · {status_icon(fails, total)} {result}")

    return rows


def recent_failures(events, dt: DateTime, limit: int = 5) -> str:
    failed = [x for x in events if int(x.status) == 0]
    failed.sort(key=lambda x: int(x.date), reverse=True)

    if not failed:
        return constant_text.STATS_RECENT_EMPTY

    rows = []
    for item in failed[:limit]:
        stamp = dt.convert_timestamp(int(item.date), "%d.%m %H:%M")["str"]
        reason = session_error_label(item.reason)
        if len(reason) > 120:
            reason = reason[:120] + "…"
        rows.append(constant_text.STATS_RECENT_ROW.format(stamp=stamp, reason=escape(reason)))

    return "\n".join(rows)


def minutes_ago(ts_value: int) -> int:
    if ts_value <= 0:
        return 0
    return max(0, int((time.time() - ts_value) // 60))
