from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import Message, Update
import pytest
import pytest_asyncio

from db.repositories.admins_repo import AdminsRepository


class OfflineSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        assert isinstance(method, (SendMessage, EditMessageText)), type(method).__name__
        return Message.model_validate({
            "message_id": getattr(method, "message_id", None) or len(self.calls), "date": 1,
            "chat": {"id": int(method.chat_id), "type": "private"}, "text": method.text,
            "reply_markup": method.reply_markup if hasattr(method.reply_markup, "inline_keyboard") else None,
        }).as_(bot)


@pytest_asyncio.fixture
async def panel(db_main, offline_module, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    for name, directory in [("handlers", "handlers"), ("handlers.admin", "handlers/admin")]:
        package = ModuleType(name)
        package.__path__ = [str(root / directory)]
        monkeypatch.setitem(sys.modules, name, package)
    loader = ModuleType("loader")
    loader.router = Router()
    loader.bot = AsyncMock()
    monkeypatch.setitem(sys.modules, "loader", loader)
    repository = AdminsRepository(db_main.get_session_factory, [1001])
    monkeypatch.setattr(db_main, "admins_repository", repository)
    module = offline_module("handlers/admin/admins_handler.py")
    for name in ("get_admin_grants", "get_admin_ids", "get_configured_admin_ids", "get_user",
                 "grant_admin", "is_admin", "revoke_admin"):
        monkeypatch.setattr(module, name, getattr(db_main, name))
    import filters.all_filters as filters
    monkeypatch.setattr(filters, "is_admin", repository.is_admin)
    gate = offline_module("middlewares/admin_access.py")
    monkeypatch.setattr(gate, "is_admin", repository.is_admin)
    profile = offline_module("middlewares/update_user.py")
    writes = AsyncMock(side_effect=db_main.update_user)
    monkeypatch.setattr(profile, "update_user", writes)
    handled = []

    @loader.router.message()
    async def other_message(message):
        handled.append(message.from_user.id)

    @loader.router.callback_query(F.data == "foreign-action")
    async def other_callback(call):
        handled.append(call.from_user.id)

    @loader.router.business_message()
    async def business(message, business_account_contexts):
        handled.append((message.from_user.id, business_account_contexts))

    dispatcher = Dispatcher()
    dispatcher.message.middleware(profile.UpdateUserMiddleware())
    dispatcher.business_message.middleware(profile.UpdateUserMiddleware())
    dispatcher.update.outer_middleware(gate.AdminAccessMiddleware())
    dispatcher.include_routers(module.router, loader.router)
    session = OfflineSession()
    bot = Bot("123456:offline_test_token", session=session)
    serial = 0

    async def feed(user_id, *, text=None, callback=None, connection=None, inaccessible=False):
        nonlocal serial
        serial += 1
        user = {"id": user_id, "is_bot": False, "first_name": "Offline"}
        message = {"message_id": serial, "date": 0 if inaccessible else 1, "chat": {"id": user_id, "type": "private"},
                   "from_user": user, "text": text or "data"}
        if callback is not None:
            if inaccessible:
                message = {key: message[key] for key in ("message_id", "date", "chat")}
            event = {"callback_query": {"id": str(serial), "from_user": user, "chat_instance": "offline",
                                        "data": callback, "message": message}}
        elif connection is not None:
            event = {"business_message": message | {"business_connection_id": connection}}
        else:
            event = {"message": message}
        await dispatcher.feed_update(bot, Update.model_validate({"update_id": serial} | event))

    def button(prefix):
        for call in reversed(session.calls):
            markup = getattr(call, "reply_markup", None)
            for row in getattr(markup, "inline_keyboard", []):
                for item in row:
                    if (item.callback_data or "").startswith(prefix):
                        return item.callback_data
        raise AssertionError(f"Missing button: {prefix}")

    try:
        yield SimpleNamespace(repository=repository, feed=feed, button=button, session=session,
                              writes=writes, handled=handled, dispatcher=dispatcher, bot=bot, module=module)
    finally:
        await dispatcher.storage.close()
        await bot.session.close()


@pytest.mark.asyncio
async def test_panel_buttons_add_confirm_revoke_and_reject_old_confirmation(panel):
    await panel.feed(1001, text=panel.module.text.MENU_BUTTON)
    await panel.feed(1001, callback=panel.button("adm:add"))
    await panel.feed(1001, text="2002")
    confirmation = panel.button("adm:grant:")
    assert not await panel.repository.is_admin(2002)
    await panel.feed(1001, callback="adm:grant:forged")
    assert not await panel.repository.is_admin(2002)
    await panel.feed(1001, callback=confirmation)
    assert await panel.repository.is_admin(2002)
    await panel.feed(2002, text="/start")
    assert 2002 in panel.handled
    await panel.feed(1001, callback="adm:revoke:2002:0")
    await panel.feed(1001, callback=panel.button("adm:remove:"))
    assert not await panel.repository.is_admin(2002)
    writes = panel.writes.await_count
    calls = len(panel.session.calls)
    await panel.feed(2002, callback="adm:add")
    assert panel.writes.await_count == writes and len(panel.session.calls) == calls
    await panel.feed(1001, callback=confirmation)
    assert not await panel.repository.is_admin(2002)


@pytest.mark.asyncio
async def test_unknown_users_cannot_write_profiles_or_use_forged_buttons(panel):
    for text in ("/start", "/admins", "👥 Администраторы", "123456"):
        await panel.feed(9999, text=text)
    for callback in ("adm:add", "adm:grant:forged", "foreign-action"):
        await panel.feed(9999, callback=callback)
    panel.writes.assert_not_awaited()
    assert not panel.session.calls and not panel.handled
    assert await panel.module.get_user(9999) is None


@pytest.mark.asyncio
async def test_revocation_during_dialog_clears_state_and_cannot_remove_another_admin(panel):
    await panel.repository.grant(1001, 2002)
    await panel.repository.grant(1001, 3003)
    await panel.feed(2002, callback="adm:revoke:1001:0")
    assert await panel.repository.is_admin(1001)
    await panel.feed(2002, callback="adm:revoke:2002:0")
    assert await panel.repository.is_admin(2002)
    await panel.feed(2002, callback="adm:revoke:3003:0")
    confirmation = panel.button("adm:remove:")
    await panel.repository.revoke(1001, 2002)
    await panel.feed(2002, callback=confirmation)
    assert await panel.repository.is_admin(3003)
    state = panel.dispatcher.fsm.get_context(bot=panel.bot, chat_id=2002, user_id=2002)
    assert await state.get_state() is None and await state.get_data() == {}


@pytest.mark.asyncio
async def test_business_gate_checks_connection_and_keeps_observed_non_admin_messages(panel, monkeypatch):
    import services.business_messages as business

    context = SimpleNamespace(owner_id=1001, account_user_id=456)
    contexts = AsyncMock(side_effect=lambda connection: [context] if connection == "tracked" else [])
    monkeypatch.setattr(business, "business_contexts", contexts)
    await panel.feed(9999, text="observed", connection="unknown")
    panel.writes.assert_not_awaited()
    await panel.feed(9999, text="observed", connection="tracked")
    panel.writes.assert_awaited_once()
    assert panel.handled == [(9999, [context])]
    assert not await panel.repository.is_admin(9999)


@pytest.mark.asyncio
async def test_list_pagination_invalid_id_and_cancel_buttons(panel):
    for user_id in range(2000, 2009):
        await panel.repository.grant(1001, user_id)
    await panel.feed(1001, text="👥 Администраторы")
    await panel.feed(1001, callback=panel.button("adm:list:1"))
    assert "Страница 2/2" in panel.session.calls[-2].text
    await panel.feed(1001, callback="adm:add")
    for value in ("@username", "-1", "0", str(2**63), "१२३"):
        await panel.feed(1001, text=value)
        assert panel.session.calls[-1].text == panel.module.text.INVALID_ID
    await panel.feed(1001, text=panel.module.text.CANCEL_BUTTON)
    state = panel.dispatcher.fsm.get_context(bot=panel.bot, chat_id=1001, user_id=1001)
    assert await state.get_state() is None
    await panel.feed(1001, callback="adm:close")
    assert isinstance(panel.session.calls[-2], EditMessageText)
    assert panel.session.calls[-2].reply_markup.inline_keyboard
    calls = len(panel.session.calls)
    await panel.feed(1001, callback="adm:add", inaccessible=True)
    assert len(panel.session.calls) == calls
