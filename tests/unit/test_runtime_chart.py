from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace

from PIL import Image
import pytest

from utils.runtime_chart import COLORS, format_duration, render_runtime_chart, runtime_summary


def row(stamp, status=1, *, component="bot", available=1, expected=1, observed_at=None):
    return SimpleNamespace(component=component, bucket_at=stamp, status=status,
                           available=available, expected=expected, observed_at=stamp if observed_at is None else observed_at)


def test_runtime_summary_keeps_unknown_time_separate_and_deduplicates_buckets():
    rows = [row(0), row(300, 3), row(600, 0, expected=0, available=0),
            row(0, observed_at=60), row(1200)]
    summary = runtime_summary(rows, "bot", 1200, seconds=1200)
    assert (summary["good"], summary["issues"], summary["disabled"], summary["unknown"]) == (300, 300, 300, 300)
    assert summary["percent"] == 50
    assert sum(summary[key] for key in ("good", "issues", "disabled", "unknown")) == 1200


def test_current_status_uses_latest_connection_not_worst_status_in_bucket():
    summary = runtime_summary([row(600, 3, observed_at=660)], "bot", 670)
    assert summary["current"] == 1 and summary["issues"] == 70
    assert runtime_summary([row(600, observed_at=660)], "bot", 900)["current"] is None
    empty = runtime_summary([], "bot", 900)
    assert empty["percent"] is None and empty["unknown"] == 86400


def test_chart_shows_short_failure_without_painting_entire_hour_red():
    start = int(datetime(2026, 11, 9, tzinfo=timezone.utc).timestamp())
    rows = [row(start + slot * 300, 3 if slot == 4 else 1) for slot in range(12)]
    now = start + 3600
    assert runtime_summary(rows, "bot", now)["percent"] == pytest.approx(100 * 11 / 12)
    image = Image.open(BytesIO(render_runtime_chart(rows, 0, now, uptime_seconds=7200)))
    # Three-day grid: the current day is the last row. An hour contains 12 strips.
    y = 138 + 143 + 2 * 26 + 8
    assert image.getpixel((116 + 2, y)) == (63, 185, 80)
    assert image.getpixel((116 + 4 * 3 + 1, y)) == (248, 81, 73)
    assert image.getpixel((116 + 11 * 3 + 1, y)) == (63, 185, 80)
    assert image.width == 1120 and image.height < 1110


def test_duration_labels_are_readable_without_seconds_noise():
    assert format_duration(2 * 86400 + 3 * 3600 + 4 * 60) == "2 д 3 ч 4 мин"
    assert format_duration(20) == "меньше минуты"
