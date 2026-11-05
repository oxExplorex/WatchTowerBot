from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import EditMessageText

from utils.panel import edit_input_panel, edit_panel


@pytest.mark.asyncio
async def test_deleted_panel_replacement_becomes_target_for_next_wizard_input():
    method = EditMessageText(chat_id=1, message_id=20, text="menu")
    bot = SimpleNamespace(edit_message_text=AsyncMock(side_effect=[
        TelegramBadRequest(method=method, message="message to edit not found"), SimpleNamespace(message_id=99),
    ]))
    message = SimpleNamespace(chat=SimpleNamespace(id=1), bot=bot,
                              answer=AsyncMock(return_value=SimpleNamespace(message_id=99)))
    state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=1, user_id=1))
    await state.update_data(panel_message_id=20)
    await edit_input_panel(message, state, "first")
    assert (await state.get_data())["panel_message_id"] == 99
    await edit_input_panel(message, state, "second")
    assert bot.edit_message_text.await_args.kwargs["message_id"] == 99
    message.answer.assert_awaited_once()
    await state.storage.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unchanged", "bad_request", "network"])
async def test_edit_does_not_duplicate_panels_on_unchanged_or_arbitrary_failure(failure):
    method = EditMessageText(chat_id=1, message_id=20, text="menu")
    error = (TelegramNetworkError(method=method, message="offline") if failure == "network" else
             TelegramBadRequest(method=method, message="message is not modified" if failure == "unchanged" else "bad markup"))
    message = SimpleNamespace(edit_text=AsyncMock(side_effect=error), answer=AsyncMock())
    if failure == "unchanged":
        await edit_panel(message, "menu")
    else:
        with pytest.raises(type(error)):
            await edit_panel(message, "menu")
    message.answer.assert_not_awaited()
