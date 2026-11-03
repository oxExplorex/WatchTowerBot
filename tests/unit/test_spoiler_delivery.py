from datetime import datetime, timezone
from pathlib import Path
import sys
import types
from unittest.mock import AsyncMock
import asyncio

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["photo", "video"])
@pytest.mark.parametrize("error", [None, RuntimeError("offline send failure"), asyncio.CancelledError()])
async def test_spoiler_and_ttl_media_are_sent_via_bot_to_creator(monkeypatch, tmp_path, offline_module, kind, error):
    from pyrogram import enums
    from pyrogram.types import Chat, Message, Photo, Video

    now = datetime.now(timezone.utc)
    media = (Photo(file_id="offline", file_unique_id="unique", width=10, height=10,
                   file_size=4, date=now) if kind == "photo" else
             Video(file_id="offline", file_unique_id="unique", width=10, height=10,
                   codec="h264", duration=1, ttl_seconds=5))
    message = Message(id=12, chat=Chat(id=789, type=enums.ChatType.PRIVATE, first_name="Offline"),
                      photo=media if kind == "photo" else None,
                      video=media if kind == "video" else None, has_media_spoiler=kind == "photo")
    filters = offline_module("filters/all_filters_app.py")
    assert filters.file_with_spoiler_or_ttl(None, None, message)
    loader = types.ModuleType("loader")
    sent = []

    async def deliver(**arguments):
        path = Path(arguments["document"].path)
        sent.append((arguments["chat_id"], path, path.read_bytes()))
        if error is not None:
            raise error

    loader.bot = types.SimpleNamespace(id=123456, send_message=AsyncMock(return_value=types.SimpleNamespace(delete=AsyncMock())),
                                       send_document=AsyncMock(side_effect=deliver))
    monkeypatch.setitem(sys.modules, "loader", loader)
    module = offline_module("handlers_app/user/file_spoiler.py")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "get_account_by_number", AsyncMock(return_value=types.SimpleNamespace(
        number="456", user_id=456, admin_id=123, is_active=1, alert_spoiler_media=1)))

    async def download(msg, file_name):
        Path(file_name).write_bytes(b"test")
        return file_name

    client = types.SimpleNamespace(name="data/session/456", download_media=AsyncMock(side_effect=download))
    if isinstance(error, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await module.file_spoiler_handler(client, message)
    else:
        await module.file_spoiler_handler(client, message)
    assert len(sent) == 1
    assert sent[0][0] == 123
    assert sent[0][2] == b"test"
    assert not sent[0][1].exists()
    loader.bot.send_document.assert_awaited_once()


@pytest.mark.asyncio
async def test_regular_media_does_not_trigger_spoiler_forwarding(offline_module):
    from pyrogram.types import Message, Photo

    module = offline_module("filters/all_filters_app.py")
    message = Message(id=12, photo=Photo(file_id="offline", file_unique_id="unique", width=1, height=1,
                                         file_size=1, date=datetime.now(timezone.utc)))
    assert not module.file_with_spoiler_or_ttl(None, None, message)
