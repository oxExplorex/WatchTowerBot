"""Pure planning for sparse message IDs; covered windows never imply deletions."""
from dataclasses import dataclass

HEAD_REFRESH_SECONDS = 6 * 60 * 60


@dataclass(frozen=True)
class HistoryWindow:
    low_id: int = 1
    high_id: int | None = None


def merge_ranges(ranges):
    merged = []
    for low, high in sorted(ranges):
        if not 1 <= low <= high:
            raise ValueError("Invalid history range")
        if merged and low <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(high, merged[-1][1]))
        else:
            merged.append((low, high))
    return merged


def plan_window(progress, ranges, now):
    ranges = merge_ranges(ranges)
    if not ranges:
        return HistoryWindow(high_id=progress.known_top_id or None)
    upper = max(progress.known_top_id, ranges[-1][1])
    holes = []
    for low, high in reversed(ranges):
        if high < upper:
            holes.append(HistoryWindow(high + 1, upper))
        upper = low - 1
    older = HistoryWindow(1, upper) if upper > 0 and not progress.reached_start else None
    # Active chats must not starve their older history indefinitely.
    if older and progress.turn % 2 == 0:
        return older
    if holes:
        return holes[0]
    if older and now - progress.last_head_at < HEAD_REFRESH_SECONDS:
        return older
    return HistoryWindow()  # Refresh the visible head without walking the whole chat.
