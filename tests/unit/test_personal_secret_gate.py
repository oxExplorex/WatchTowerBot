import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from middlewares.personal_secret import (PersonalSecretMiddleware, SECRET_CONFIRM, SECRET_INPUT,
                                         SECRET_VERIFY, SETUP_CALLBACK, INPUT_PROMPT)


def message(text="/start"):
    return SimpleNamespace(text=text, chat=SimpleNamespace(id=123, type="private"),
                           answer=AsyncMock(), delete=AsyncMock())


def update(msg=None, call=None, business=None):
    return SimpleNamespace(message=msg, edited_message=None, callback_query=call,
                           business_message=business, edited_business_message=None, deleted_business_messages=None)


def context(state):
    return {"state": state, "event_from_user": SimpleNamespace(id=123), "bot": SimpleNamespace(id=1, send_message=AsyncMock())}


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setitem(sys.modules, "utils.others", SimpleNamespace(close_state_pyrogram_client=AsyncMock()))
    repository = SimpleNamespace(get=AsyncMock(return_value=None), install=AsyncMock(return_value=True))
    state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=123, user_id=123))
    gate = PersonalSecretMiddleware(repository, authorize=AsyncMock(return_value=True))
    return repository, state, gate


@pytest.mark.asyncio
async def test_onboarding_confirms_without_plaintext_in_fsm_and_deletes_every_entry(setup):
    repository, state, gate = setup
    handler, data = AsyncMock(), context(state)
    await gate(handler, update(message()), data)
    handler.assert_not_awaited()
    data["bot"].send_message.assert_awaited_once()
    call = SimpleNamespace(data=SETUP_CALLBACK, message=message(), answer=AsyncMock())
    await gate(handler, update(call=call), data)
    assert await state.get_state() == SECRET_INPUT
    first = message("Рыжий кот 527")
    await gate(handler, update(first), data)
    first.delete.assert_awaited_once()
    assert await state.get_state() == SECRET_CONFIRM
    stored = str(await state.get_data())
    assert "Рыжий" not in stored and "рыжийкот527" not in stored
    wrong = message("Другой секрет 987")
    await gate(handler, update(wrong), data)
    wrong.delete.assert_awaited_once()
    repository.install.assert_not_awaited()
    correct = message("рыжийКОТ527")
    await gate(handler, update(correct), data)
    correct.delete.assert_awaited_once()
    repository.install.assert_awaited_once()
    assert await state.get_state() is None and await state.get_data() == {}
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_reply_with_secret_after_restart_is_deleted_before_ordinary_handlers(setup):
    repository, state, gate = setup
    repository.get.return_value = SimpleNamespace(public_key="offline")
    msg = message("Личныйсекрет592")
    msg.reply_to_message = SimpleNamespace(from_user=SimpleNamespace(id=1), text=INPUT_PROMPT)
    handler = AsyncMock()
    await gate(handler, update(msg), context(state))
    msg.delete.assert_awaited_once()
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_undeleted_secret_is_rejected_without_key_generation_or_handler(setup):
    repository, state, gate = setup
    await state.set_state(SECRET_INPUT)
    await state.update_data(secret_expires=int(time.time()) + 60)
    msg = message("Новыйсекрет527")
    msg.delete.side_effect = RuntimeError("offline deletion denied")
    handler = AsyncMock()
    gate._crypto = AsyncMock()
    await gate(handler, update(msg), context(state))
    gate._crypto.assert_not_awaited()
    repository.install.assert_not_awaited()
    gate._attempts.clear()
    gate.authorize.return_value = False
    gate._crypto.return_value = object()
    await state.set_state(SECRET_CONFIRM)
    await state.update_data(secret_bundle={"public_key": "offline"})
    await gate(AsyncMock(), update(message("Новыйсекрет527")), context(state))
    repository.install.assert_not_awaited()
    assert await state.get_state() is None
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_business_capture_continues_without_secret_but_control_and_group_are_blocked(setup):
    repository, state, gate = setup
    handler = AsyncMock(return_value="stored")
    assert await gate(handler, update(business=SimpleNamespace()), context(state)) == "stored"
    repository.get.assert_not_awaited()
    handler.reset_mock()
    msg = message()
    msg.chat.type = "group"
    await gate(handler, update(msg), context(state))
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_requires_confirmation_while_delete_does_not_and_entry_preserves_permit(setup):
    repository, state, gate = setup
    repository.get.return_value = SimpleNamespace(public_key="offline")
    handler = AsyncMock()
    call = SimpleNamespace(data="apps_admin_menu_add", message=message(), answer=AsyncMock())
    await gate(handler, update(call=call), context(state))
    assert await state.get_state() == SECRET_VERIFY
    handler.assert_not_awaited()
    await state.clear()
    call.data = "account_admin_menu_delete:offline"
    await gate(handler, update(call=call), context(state))
    handler.assert_awaited_once()
    until = int(time.time()) + 600
    await state.update_data(personal_verified_until=until)

    async def start_wizard(*args):
        await state.clear()
        await state.set_state("AdminStates:apps_add_app_id")

    call.data = "apps_admin_menu_add"
    await gate(start_wizard, update(call=call), context(state))
    assert (await state.get_data())["personal_verified_until"] == until


@pytest.mark.asyncio
async def test_cancel_expiry_rate_limit_and_revocation_do_not_install_key(setup):
    repository, state, gate = setup
    for content in ("/cancel", "Новыйсекрет527"):
        await state.set_state(SECRET_INPUT)
        await state.update_data(secret_expires=0)
        msg = message(content)
        await gate(AsyncMock(), update(msg), context(state))
        msg.delete.assert_awaited_once()
        assert await state.get_state() is None
    await state.set_state(SECRET_INPUT)
    await state.update_data(secret_expires=int(time.time()) + 60)
    for _ in range(5):
        await gate(AsyncMock(), update(message("123456")), context(state))
    gate._crypto = AsyncMock()
    await gate(AsyncMock(), update(message("Новыйсекрет527")), context(state))
    gate._crypto.assert_not_awaited()
    repository.install.assert_not_awaited()
