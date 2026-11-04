import asyncio
import sys
import types
from unittest.mock import AsyncMock, Mock

from aiogram import Bot, Dispatcher, Router
from aiogram.types import Update
import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,batch_size", [("business_message", 1), ("edited_business_message", 1),
                                           ("deleted_business_messages", 1), ("business_message", 3)])
async def test_business_updates_are_routed_with_current_sdk(monkeypatch, offline_module, kind, batch_size):
    loader = types.ModuleType("loader")
    loader.router = Router()
    loader.bot = AsyncMock()
    loader.bot.get_business_connection.return_value.user.id = 123
    monkeypatch.setitem(sys.modules, "loader", loader)
    filenames = {
        "business_message": "business_handler.py",
        "edited_business_message": "business_edit_handler.py",
        "deleted_business_messages": "business_del_handler.py",
    }
    module = offline_module("handlers/user/business/" + filenames[kind])
    monkeypatch.setattr(module, "business_contexts", AsyncMock(return_value=[types.SimpleNamespace(owner_id=123, account_user_id=456)]))
    record = AsyncMock()
    monkeypatch.setattr(module, "delete_message" if kind == "deleted_business_messages" else "save_message", record)
    chat = {"id": 456, "type": "private", "first_name": "Offline"}
    event = {"business_connection_id": "offline-connection", "chat": chat}
    if kind == "deleted_business_messages":
        event["message_ids"] = [12, 13]
    else:
        event.update(message_id=12, date=1, text="synthetic-private", from_user={"id": 456, "is_bot": False, "first_name": "Offline"})
    if batch_size > 1:
        event["media_group_id"] = "offline-album"
    updates = [Update.model_validate({"update_id": 100 + index, kind: event | (
        {"message_id": 12 + index} if kind != "deleted_business_messages" else {})}) for index in range(batch_size)]
    dispatcher = Dispatcher()
    dispatcher.include_router(module.router)
    bot = Bot("123456:offline_test_token")
    try:
        await asyncio.gather(*(dispatcher.feed_update(bot, update) for update in updates))
    finally:
        await dispatcher.storage.close()
        await bot.session.close()
    assert record.await_count == (2 if kind == "deleted_business_messages" else batch_size)
    assert all(call.kwargs["source"] == "business" for call in record.await_args_list)
    assert {call.kwargs["event_key"] for call in record.await_args_list} == {
        f"offline-connection:{100 + index}" for index in range(batch_size)}
