import asyncio
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.methods import GetMe, GetUpdates

from core.session_diagnostics import session_error_code
from utils.datetime_tools import DateTime
from utils.settings_formatting import build_daily_rows_desc, build_hourly_rows_desc


@pytest.mark.parametrize("detail,expected", [
    ("database is locked", "sqlite_locked"), ("no such column: x", "sqlite_schema"),
    ("unable to open database file", "sqlite_open"), ("attempt to write a readonly database", "sqlite_readonly"),
    ("database or disk is full", "sqlite_full"), ("database disk image is malformed", "sqlite_corrupt"),
])
def test_sqlite_failure_classification(detail, expected):
    assert session_error_code(sqlite3.OperationalError(detail)) == expected


@pytest.mark.asyncio
async def test_polling_tracker_observes_only_getupdates_and_preserves_errors_until_sample(offline_module):
    service = offline_module("services/runtime_health.py")
    tracker = service.PollingHealth()
    request = AsyncMock(return_value=[])
    assert tracker.available(1000) is None
    await tracker(request, object(), GetMe())
    assert tracker.available(1000) is None
    request.side_effect = OSError("synthetic network error")
    with pytest.raises(OSError):
        await tracker(request, object(), GetUpdates())
    request.side_effect = None
    await tracker(request, object(), GetUpdates())
    assert tracker.available(tracker.last_success) == 0
    tracker.failed_since_sample = False
    assert tracker.available(tracker.last_success) == 1
    request.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await tracker(request, object(), GetUpdates())
    assert tracker.failures == 1


def test_empty_checks_are_not_reported_as_zero_uptime_and_daily_period_is_explicit():
    class Clock(DateTime):
        def now(self):
            return datetime(2026, 11, 5, 17, 37, tzinfo=timezone.utc)
    clock = Clock(0)
    previous_morning = SimpleNamespace(date=int(datetime(2026, 11, 4, 8, tzinfo=timezone.utc).timestamp()), status=1)
    hourly = build_hourly_rows_desc([previous_morning], 24, clock)
    daily = build_daily_rows_desc([previous_morning], 1, clock)
    assert all("нет проверок" in row and "0%" not in row for row in hourly)
    assert "04.11 00:00 → 05.11 00:00" in daily[0] and "100% (1 проверок)" in daily[0]
