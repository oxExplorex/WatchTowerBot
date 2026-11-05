import asyncio
from types import SimpleNamespace, MethodType
from unittest.mock import AsyncMock
import logging

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
async def test_public_history_adapter_preserves_window_and_empty_ids(offline_module):
    module = offline_module("services/history_backfill.py")
    calls = []
    async def get_chat_history(chat_id, **kwargs):
        calls.append((chat_id, kwargs))
        yield SimpleNamespace(id=80, empty=False, chat=SimpleNamespace(id=123, type="private"))
        yield SimpleNamespace(id=75, empty=True)
        yield SimpleNamespace(id=70, empty=False, chat=SimpleNamespace(id=123, type="private"))
    client = SimpleNamespace(get_chat_history=get_chat_history)
    ids, messages = await module.fetch_history_page(client, 123, HistoryWindow(70, 80))
    assert ids == [80, 75, 70] and [item.id for item in messages] == [80, 70]
    assert calls == [(123, {"limit": 100, "min_id": 70, "max_id": 80})]
    calls.clear()
    assert await module.fetch_history_page(client, -100123, HistoryWindow()) is None
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("error_name", ["PeerIdInvalid", "FloodWait"])
async def test_public_history_preserves_errors_without_duplicate_logs(offline_module, caplog, error_name):
    from pyrogram.errors import PeerIdInvalid, FloodWait

    module = offline_module("services/history_backfill.py")
    caplog.set_level(logging.DEBUG, logger=module.bot_logger.name)
    error = PeerIdInvalid() if error_name == "PeerIdInvalid" else FloodWait(120)
    async def get_chat_history(*args, **kwargs):
        raise error
        yield  # Async generator, like the public SDK method.
    client = SimpleNamespace(get_chat_history=get_chat_history)
    with pytest.raises(type(error)) as failure:
        await module.fetch_history_page(client, 123, HistoryWindow(70, 80))
    assert failure.value is error
    assert not caplog.records  # The account worker logs the failure once, with context.


@pytest.mark.asyncio
@pytest.mark.parametrize("flood", [False, True])
async def test_real_kurigram_history_sends_request_and_propagates_long_floodwait(offline_module, monkeypatch, flood):
    from pyrogram import Client, raw, utils
    from pyrogram.errors import FloodWait
    from pyrogram.session import Session
    module = offline_module("services/history_backfill.py")
    ready = asyncio.Event()
    ready.set()
    response = SimpleNamespace(messages=[], users=[], chats=[])
    transport = SimpleNamespace(is_started=ready, WAIT_TIMEOUT=1, send=AsyncMock(return_value=response))
    transport.invoke = MethodType(Session.invoke, transport)
    client = SimpleNamespace(is_connected=True, no_updates=False, takeout_id=None,
        session=transport, fetch_peers=AsyncMock(),
        resolve_peer=AsyncMock(return_value=raw.types.InputPeerUser(user_id=123, access_hash=1)))
    client.invoke = MethodType(Client.invoke, client)
    client.get_chat_history = MethodType(Client.get_chat_history, client)
    parser = AsyncMock(return_value=[])
    monkeypatch.setattr(utils, "parse_messages", parser)
    if flood:
        transport.send.side_effect = FloodWait(120)
        with pytest.raises(FloodWait):
            await module.fetch_history_page(client, 123, HistoryWindow(70, 80))
        parser.assert_not_awaited()
    else:
        assert await module.fetch_history_page(client, 123, HistoryWindow(70, 80)) == ([], [])
        assert parser.await_args.kwargs["replies"] == 0
    transport.send.assert_awaited_once()
    request = transport.send.await_args.args[0]
    assert isinstance(request, raw.functions.messages.GetHistory)
    assert (request.offset_id, request.min_id, request.max_id, request.limit) == (81, 69, 81, 100)


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_type, chat_id, message_id", [
    ("bot", 123, 75), ("private", 456, 75), ("private", 123, 81)])
async def test_public_history_rejects_wrong_chat_and_out_of_window_messages(
        offline_module, chat_type, chat_id, message_id):
    module = offline_module("services/history_backfill.py")
    async def get_chat_history(*args, **kwargs):
        yield SimpleNamespace(id=message_id, empty=False, chat=SimpleNamespace(id=chat_id, type=chat_type))
    client = SimpleNamespace(get_chat_history=get_chat_history)
    if message_id == 81:
        with pytest.raises(ValueError, match="outside requested window"):
            await module.fetch_history_page(client, 123, HistoryWindow(70, 80))
    else:
        assert await module.fetch_history_page(client, 123, HistoryWindow(70, 80)) is None
