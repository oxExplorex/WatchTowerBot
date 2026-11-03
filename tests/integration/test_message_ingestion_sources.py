from datetime import datetime, timezone
import sys
import types
from unittest.mock import AsyncMock

from aiogram.types import Message as BotMessage
import pytest
from sqlalchemy import select

from db.message_models import MessageRevision, StoredMessage


@pytest.mark.asyncio
async def test_business_and_userbot_payloads_share_storage_and_one_notification(db_main, monkeypatch):
    from services import message_service
    from pyrogram import enums
    from pyrogram.types import Chat, Message, User

    monkeypatch.setattr(message_service, "messages_repository", db_main.messages_repository)
    monkeypatch.setattr(message_service, "update_user", AsyncMock())
    bot = types.SimpleNamespace(id=123456, send_message=AsyncMock())
    context = message_service.AccountContext(123, 456)
    api_message = BotMessage.model_validate({"message_id": 12, "date": 100,
        "chat": {"id": 789, "type": "private", "first_name": "Offline"},
        "from": {"id": 789, "is_bot": False, "first_name": "Offline"}, "text": "Private"})
    user_message = Message(id=12, date=datetime.fromtimestamp(100, timezone.utc), text="Private",
        chat=Chat(id=789, type=enums.ChatType.PRIVATE, first_name="Offline"), from_user=User(id=789, first_name="Offline"))
    await message_service.save_message(bot, context, api_message, source="business", kind="new", event_key="b:1")
    await message_service.save_message(bot, context, user_message, source="userbot", kind="new", event_key="u:1")
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.args[0] == 123
    async with db_main.create_unit_of_work() as uow:
        assert len((await uow.session.scalars(select(StoredMessage))).all()) == 1
        assert len((await uow.session.scalars(select(MessageRevision))).all()) == 1


@pytest.mark.asyncio
async def test_control_bot_dialogue_is_not_archived(db_main, monkeypatch):
    from services import message_service

    store = AsyncMock()
    monkeypatch.setattr(message_service, "messages_repository", store)
    message = BotMessage.model_validate({"message_id": 12, "date": 100,
        "chat": {"id": 123456, "type": "private", "first_name": "Control"}, "text": "secret"})
    await message_service.save_message(types.SimpleNamespace(id=123456), message_service.AccountContext(123, 456),
                                       message, source="userbot", kind="new")
    store.record.assert_not_awaited()
