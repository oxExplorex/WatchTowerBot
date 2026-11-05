from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.history_windows import HistoryWindow, merge_ranges, plan_window


def test_windows_target_exact_holes_and_do_not_require_message_one():
    progress = SimpleNamespace(known_top_id=100, reached_start=True, turn=1, last_head_at=10000)
    assert plan_window(progress, [(1, 69), (81, 100)], 10001) == HistoryWindow(70, 80)
    progress = SimpleNamespace(known_top_id=6000, reached_start=False, turn=2, last_head_at=10000)
    assert plan_window(progress, [(5000, 6000)], 10001) == HistoryWindow(1, 4999)
    progress.reached_start = True
    assert plan_window(progress, [(1, 6000)], 10001) == HistoryWindow()
    assert merge_ranges([(81, 100), (70, 80), (1, 69), (75, 85)]) == [(1, 100)]


@pytest.mark.asyncio
async def test_raw_adapter_bounds_one_request_and_does_not_fetch_replies(offline_module, monkeypatch):
    from pyrogram import raw

    module = offline_module("services/history_backfill.py")
    client = SimpleNamespace(resolve_peer=AsyncMock(return_value=raw.types.InputPeerUser(user_id=123, access_hash=1)),
                             invoke=AsyncMock(return_value=SimpleNamespace(messages=[SimpleNamespace(id=75)])))
    parser = AsyncMock(return_value=[SimpleNamespace(id=75, empty=False, chat=SimpleNamespace(id=123, type="private"))])
    monkeypatch.setattr(module.utils, "parse_messages", parser)
    ids, messages = await module.fetch_history_page(client, 123, HistoryWindow(70, 80))
    assert ids == [75] and len(messages) == 1
    request = client.invoke.await_args.args[0]
    assert (request.offset_id, request.max_id, request.min_id, request.limit) == (81, 81, 69, 100)
    assert client.invoke.await_count == 1 and client.invoke.await_args.kwargs == {"sleep_threshold": 0, "retries": 0}
    assert parser.await_args.kwargs["replies"] == 0
    client.invoke.reset_mock()
    assert await module.fetch_history_page(client, -100123, HistoryWindow()) is None
    client.invoke.assert_not_awaited()
