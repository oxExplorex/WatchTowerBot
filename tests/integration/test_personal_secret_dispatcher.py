import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.methods import AnswerCallbackQuery, DeleteMessage, EditMessageText, SendMessage
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
        assert isinstance(method, (SendMessage, EditMessageText))
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
    monkeypatch.setitem(sys.modules, "utils.others", SimpleNamespace(close_state_pyrogram_client=AsyncMock(),
                                                                 not_warning_delete_message=AsyncMock()))
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
    ownership = offline_module("handlers/user/account_ownership.py")
    import filters.all_filters as access_filters
    monkeypatch.setattr(access_filters, "is_admin", repository.is_admin)
    ownership.is_admin = repository.is_admin
    ownership.get_app_tg_user_id = db_main.get_app_tg_user_id
    from services import account_access
    monkeypatch.setattr(account_access, "is_admin", repository.is_admin)
    apps = offline_module("handlers/admin/apps_manager/apps_add_handler.py")
    apps.create_app_tg = db_main.create_app_tg
    apps.get_app_tg_to_params_all = db_main.get_app_tg_to_params_all
    apps.not_warning_delete_message = AsyncMock()
    dispatcher = Dispatcher(events_isolation=SimpleEventIsolation())
    dispatcher.update.outer_middleware(admission.AdminAccessMiddleware())
    dispatcher.update.outer_middleware(AuthSessionCleanupMiddleware())
    dispatcher.update.outer_middleware(PersonalSecretMiddleware(keys, account_access.can_use_secret))
    dispatcher.include_router(ownership.router)
    dispatcher.include_router(apps.router)
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
                              state=lambda uid=1001: dispatcher.fsm.get_context(bot=bot, chat_id=uid, user_id=uid),
                              db=db_main, ownership=ownership, bot=bot)
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
    await flow.feed(callback="personal_secret:setup")
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
async def test_limited_user_can_create_only_own_profile_after_secret_verification(setup_flow):
    from core.personal_crypto import create_key_bundle
    import time

    flow = setup_flow
    await flow.db.create_app_tg(1001, 12345, "foreign-synthetic-hash", "owner")
    app = (await flow.db.get_app_tg_user_id(1001))[0][0]
    await flow.db.create_account_tg(1001, 2002, app.uuid, "79000000001")
    await flow.keys.install(2002, create_key_bundle(2002, "Личныйсекрет2002"))
    await flow.state(2002).update_data(personal_verified_until=int(time.time()) + 600)
    await flow.feed(2002, callback="apps_admin_menu_add")
    await flow.feed(2002, content="23456")
    await flow.feed(2002, content="own-synthetic-hash")
    await flow.feed(2002, content="Моё приложение")
    await flow.feed(2002, callback="agree")
    profiles, count = await flow.db.get_app_tg_user_id(2002)
    assert count == 1 and profiles[0].api_hash == "own-synthetic-hash"
    assert (await flow.db.get_app_tg_user_id(1001))[1] == 1
    assert not await flow.admins.is_admin(2002)
    assert "foreign-synthetic-hash" not in str(flow.session.calls)


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


@pytest.mark.asyncio
async def test_limited_self_view_hides_foreign_profile_and_deletion_survives_fsm_reset(setup_flow):
    from callbacks.account_ownership import OwnAccount
    from db.repositories.account_operations_repo import AccountOperationsRepository

    flow = setup_flow
    await flow.db.create_app_tg(1001, 12345, "never-display-foreign-hash", "private app")
    app = (await flow.db.get_app_tg_user_id(1001))[0][0]
    account = await flow.db.create_account_tg(1001, 2002, app.uuid, "79000000001")
    pack = lambda action, token="-": OwnAccount(action=action, token=str(token)).pack()
    await flow.feed(2002, content="/start")
    await flow.feed(2002, callback=pack("detail", account.uuid.hex))
    assert "never-display-foreign-hash" not in str(flow.session.calls)
    assert flow.handled == []
    count = len(flow.session.calls)
    await flow.feed(9999, callback=pack("delete", account.uuid.hex))
    assert len(flow.session.calls) == count
    await flow.feed(2002, callback=f"acc:e:{account.uuid}")
    assert "never-display-foreign-hash" not in str(flow.session.calls)
    assert flow.handled == []  # Secret gate prevents entry into ordinary management.
    await flow.feed(2002, callback=pack("delete", account.uuid.hex))
    warning = next(call for call in reversed(flow.session.calls) if isinstance(call, SendMessage))
    confirm = warning.reply_markup.inline_keyboard[0][0].callback_data
    operation_id = OwnAccount.unpack(confirm).token
    await flow.state(2002).clear()  # Simulates loss of short-lived FSM across restart.
    await flow.feed(2002, callback=confirm)
    operation = await AccountOperationsRepository(flow.db.get_session_factory).get(operation_id, 2002)
    assert operation.status == "deleting"
    assert (await flow.db.get_account_uuid(account.uuid, 1001)).is_active == 0


@pytest.mark.asyncio
async def test_transfer_approval_deletes_secret_before_starting_task(setup_flow, monkeypatch):
    from callbacks.account_ownership import OwnAccount
    from core.personal_crypto import create_key_bundle
    from services import account_operations
    from db.repositories.account_operations_repo import AccountOperationsRepository
    from states.personal_secret import SECRET_TRANSFER

    flow = setup_flow
    for uid in (1001, 2002):
        await flow.db.create_app_tg(uid, uid + 10000, f"synthetic-{uid}", "app")
        await flow.keys.install(uid, create_key_bundle(uid, f"Личныйсекрет{uid}"))
    app = (await flow.db.get_app_tg_user_id(1001))[0][0]
    target = (await flow.db.get_app_tg_user_id(2002))[0][0]
    account = await flow.db.create_account_tg(1001, 2002, app.uuid, "79000000001")
    operations = AccountOperationsRepository(flow.db.get_session_factory)
    operation = await operations.request_transfer(account.uuid, 2002, target.uuid)
    await flow.feed(callback=OwnAccount(action="approve", token=operation.uuid.hex).pack())
    assert await flow.state().get_state() == SECRET_TRANSFER

    async def start(bot, operation_id, owner_id, private):
        assert isinstance(flow.session.calls[-1], DeleteMessage)
        assert str(operation_id) == str(operation.uuid) and owner_id == 1001
        assert private is not None
        return True

    starter = AsyncMock(side_effect=start)
    monkeypatch.setattr(account_operations, "start_transfer", starter)
    await flow.feed(content="Личныйсекрет1001")
    starter.assert_awaited_once()
    assert await flow.state().get_state() is None
    assert "Личныйсекрет1001" not in str(flow.session.calls)
    assert flow.handled == []
