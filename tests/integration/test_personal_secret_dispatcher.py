import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.methods import AnswerCallbackQuery, DeleteMessage, SendMessage
from aiogram.types import Message, Update
import pytest
import pytest_asyncio

from db.repositories.admins_repo import AdminsRepository
from db.repositories.personal_repo import PersonalKeyRepository
from middlewares.auth_session_cleanup import AuthSessionCleanupMiddleware
from middlewares.personal_secret import PersonalSecretMiddleware, SECRET_CONFIRM, SECRET_INPUT, SETUP_CALLBACK


class OfflineSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        raise AssertionError("No media in secret setup")
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (AnswerCallbackQuery, DeleteMessage)):
            return True
        assert isinstance(method, SendMessage)
        return Message.model_validate({"message_id": len(self.calls), "date": 1,
            "chat": {"id": int(method.chat_id), "type": "private"}, "text": method.text,
            "from_user": {"id": bot.id, "is_bot": True, "first_name": "Offline bot"}})


@pytest_asyncio.fixture
async def setup_flow(db_main, offline_module, monkeypatch):
    repository = AdminsRepository(db_main.get_session_factory, [1001])
    monkeypatch.setattr(db_main, "admins_repository", repository)
    loader = ModuleType("loader")
    loader.router = Router()
    monkeypatch.setitem(sys.modules, "loader", loader)
    monkeypatch.setitem(sys.modules, "utils.others", SimpleNamespace(close_state_pyrogram_client=AsyncMock()))
    admission = offline_module("middlewares/admin_access.py")
    admission.is_admin = repository.is_admin
    profile = offline_module("middlewares/update_user.py")
    writes = AsyncMock(side_effect=db_main.update_user)
    profile.update_user = writes
    loader.router.message.middleware(profile.UpdateUserMiddleware())
    handled = []

    @loader.router.message()
    async def ordinary_handler(message):
        handled.append(message.text)

    keys = PersonalKeyRepository(db_main.get_session_factory)
    dispatcher = Dispatcher(events_isolation=SimpleEventIsolation())
    dispatcher.update.outer_middleware(admission.AdminAccessMiddleware())
    dispatcher.update.outer_middleware(AuthSessionCleanupMiddleware())
    dispatcher.update.outer_middleware(PersonalSecretMiddleware(keys, repository.is_admin))
    dispatcher.include_router(loader.router)
    session = OfflineSession()
    bot = Bot("123456:offline_test_token", session=session)
    serial = 0

    async def feed(user_id=1001, *, content=None, callback=None, inaccessible=False):
        nonlocal serial
        serial += 1
        user = {"id": user_id, "is_bot": False, "first_name": "Offline admin"}
        message = {"message_id": serial, "date": 0 if inaccessible else 1,
                   "chat": {"id": user_id, "type": "private"}, "from_user": user, "text": content or "old menu"}
        if callback is not None:
            if inaccessible:
                message = {key: message[key] for key in ("message_id", "date", "chat")}
            payload = {"callback_query": {"id": str(serial), "from_user": user, "chat_instance": "offline",
                                          "data": callback, "message": message}}
        else:
            payload = {"message": message}
        await dispatcher.feed_update(bot, Update.model_validate({"update_id": serial} | payload))
        return serial

    try:
        yield SimpleNamespace(feed=feed, keys=keys, admins=repository, handled=handled, session=session, writes=writes,
                              state=lambda uid=1001: dispatcher.fsm.get_context(bot=bot, chat_id=uid, user_id=uid))
    finally:
        await dispatcher.storage.close()
        await dispatcher.fsm.events_isolation.close()
        await bot.session.close()


@pytest.mark.asyncio
async def test_real_dispatcher_setup_deletes_inputs_before_profile_writes_and_handles_old_button(setup_flow):
    flow = setup_flow
    await flow.feed(9999, content="Нельзяпропустить527")
    assert not flow.session.calls
    await flow.feed(content="/start")
    flow.writes.assert_not_awaited()
    await flow.feed(callback=SETUP_CALLBACK)
    assert await flow.state().get_state() == SECRET_INPUT
    first = await flow.feed(content="Рыжий кот 527")
    assert await flow.state().get_state() == SECRET_CONFIRM
    assert await flow.keys.get(1001) is None
    assert "рыжийкот527" not in str(await flow.state().get_data())
    second = await flow.feed(content="рыжийКОТ527")
    assert await flow.keys.get(1001) is not None
    assert {call.message_id for call in flow.session.calls if isinstance(call, DeleteMessage)} == {first, second}
    assert "Рыжий кот 527" not in str(flow.session.calls)
    flow.writes.assert_not_awaited()
    assert flow.handled == []
    await flow.feed(content="/start")
    assert flow.handled == ["/start"]
    flow.writes.assert_awaited_once()
    await flow.feed(callback=SETUP_CALLBACK, inaccessible=True)
    assert isinstance(flow.session.calls[-1], AnswerCallbackQuery)


@pytest.mark.asyncio
async def test_revocation_during_secret_input_still_deletes_secret_and_clears_fsm(setup_flow):
    flow = setup_flow
    await flow.admins.grant(1001, 2002)
    await flow.feed(2002, callback=SETUP_CALLBACK)
    assert await flow.state(2002).get_state() == SECRET_INPUT
    await flow.admins.revoke(1001, 2002)
    message_id = await flow.feed(2002, content="Личныйсекрет592")
    assert isinstance(flow.session.calls[-1], DeleteMessage)
    assert flow.session.calls[-1].message_id == message_id
    assert await flow.state(2002).get_state() is None and await flow.state(2002).get_data() == {}
    assert await flow.keys.get(2002) is None
    flow.writes.assert_not_awaited()
