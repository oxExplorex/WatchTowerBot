from datetime import datetime, timezone
from pathlib import Path
import sys
import types
from unittest.mock import AsyncMock
import asyncio

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("use_topics", [False, True])
@pytest.mark.parametrize("kind", ["photo", "video", "video_note"])
@pytest.mark.parametrize("error", [None, RuntimeError("offline send failure"), asyncio.CancelledError()])
async def test_spoiler_and_ttl_media_are_sent_via_bot_to_creator(monkeypatch, tmp_path, offline_module, kind, error, use_topics):
    from pyrogram import enums
    from pyrogram.types import Chat, Message, Photo, User, Video, VideoNote

    now = datetime.now(timezone.utc)
    if kind == "photo":
        media = Photo(file_id="offline", file_unique_id="unique", width=10, height=10, file_size=4, date=now)
    elif kind == "video":
        media = Video(file_id="offline", file_unique_id="unique", width=10, height=10,
                      codec="h264", duration=1, ttl_seconds=5)
    else:
        media = VideoNote(file_id="offline", file_unique_id="unique", length=10, duration=1, ttl_seconds=5)
    message = Message(id=12, chat=Chat(id=789, type=enums.ChatType.PRIVATE, first_name="Чат & <друг>"),
                      from_user=User(id=789, first_name="Данил & <друг>"),
                      photo=media if kind == "photo" else None,
                      video=media if kind == "video" else None,
                      video_note=media if kind == "video_note" else None, has_media_spoiler=kind == "photo")
    filters = offline_module("filters/all_filters_app.py")
    assert filters.file_with_spoiler_or_ttl(None, None, message)
    loader = types.ModuleType("loader")
    sent = []

    async def deliver(**arguments):
        path = Path(arguments[kind].path)
        sent.append((arguments["chat_id"], path, path.read_bytes()))
        if error is not None:
            raise error
        return types.SimpleNamespace(message_id=900, message_thread_id=arguments.get("message_thread_id"))

    status = types.SimpleNamespace(delete=AsyncMock(), edit_text=AsyncMock())
    loader.bot = types.SimpleNamespace(id=123456, send_message=AsyncMock(return_value=status), send_document=AsyncMock(),
        send_photo=AsyncMock(side_effect=deliver), send_video=AsyncMock(side_effect=deliver),
        send_video_note=AsyncMock(side_effect=deliver))
    monkeypatch.setitem(sys.modules, "loader", loader)
    module = offline_module("handlers_app/user/file_spoiler.py")
    from services.notification_topics import TopicDelivery
    repository = types.SimpleNamespace(get=AsyncMock(return_value=77), save=AsyncMock())
    loader.bot.get_me = AsyncMock(return_value=types.SimpleNamespace(has_topics_enabled=use_topics))
    loader.bot._watchtower_topic_delivery = TopicDelivery(loader.bot, repository)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "get_account_by_number", AsyncMock(return_value=types.SimpleNamespace(
        number="79990000000", user_id=456, admin_id=123, is_active=1, alert_spoiler_media=1)))

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
    sender = getattr(loader.bot, f"send_{kind}")
    sender.assert_awaited_once()
    loader.bot.send_document.assert_not_awaited()
    assert sender.call_args.kwargs.get("message_thread_id") == (77 if use_topics else None)
    if error is None:
        if kind == "video_note":
            metadata = loader.bot.send_message.call_args.kwargs
            assert metadata["reply_parameters"].message_id == 900
            assert metadata["message_thread_id"] == (77 if use_topics else None)
            caption = metadata["text"]
            assert "caption" not in sender.call_args.kwargs
        else:
            caption = sender.call_args.kwargs["caption"]
            assert sender.call_args.kwargs["parse_mode"] == "HTML"
            assert loader.bot.send_message.await_count == 1  # Only the temporary download status.
        assert "<b>Временное" in caption and "<b>Аккаунт:</b>" in caption
        assert "Данил &amp; &lt;друг&gt;" in caption and "Чат &amp; &lt;друг&gt;" in caption
        assert "&amp;amp;" not in caption and "79990000000" not in caption
        assert caption.count("456") == 2  # One linked ID: href plus visible text.
        status.delete.assert_awaited_once()
    if kind == "video":
        assert sender.call_args.kwargs["supports_streaming"] is True


@pytest.mark.asyncio
async def test_regular_media_does_not_trigger_spoiler_forwarding(offline_module):
    from pyrogram.types import Message, Photo

    module = offline_module("filters/all_filters_app.py")
    message = Message(id=12, photo=Photo(file_id="offline", file_unique_id="unique", width=1, height=1,
                                         file_size=1, date=datetime.now(timezone.utc)))
    assert not module.file_with_spoiler_or_ttl(None, None, message)
