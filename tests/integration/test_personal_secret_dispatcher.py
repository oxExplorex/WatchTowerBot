import sys
import asyncio
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery, CreateForumTopic, DeleteMessage, EditMessageMedia, EditMessageText, SendDocument, SendMessage, SendPhoto
from aiogram.types import ForumTopic, Message, ReplyKeyboardRemove, Update
import pytest
import pytest_asyncio

from db.repositories.admins_repo import AdminsRepository
from db.repositories.personal_repo import PersonalKeyRepository
from middlewares.auth_session_cleanup import AuthSessionCleanupMiddleware
from middlewares.personal_secret import PersonalSecretMiddleware, SECRET_CONFIRM, SECRET_INPUT, SETUP_CALLBACK


@pytest.mark.asyncio
@pytest.mark.parametrize("navigate", [False, True])
async def test_dump_button_accepts_chat_id_and_rejects_foreign_chat(setup_flow, monkeypatch, navigate):
    from core.personal_crypto import create_key_bundle
    from states.backups import DUMP_CHAT_ID
    flow = setup_flow
    await flow.keys.install(1001, create_key_bundle(1001, "Личныйсекрет1001"))
    await flow.db.messages_repository.record(owner_id=1001, account_user_id=456, chat_id=789,
        message_id=1, kind="new", source="business", event_key="one", payload={"text": "private", "media": []})
    worker = AsyncMock()
    monkeypatch.setattr(flow.backups, "_dump", worker)
    await flow.feed(callback="backup:menu")
    await flow.feed(callback="backup:dump")
    assert await flow.state().get_state() == DUMP_CHAT_ID
    invalid_input = await flow.feed(content="не айди")
    assert any(isinstance(call, DeleteMessage) and call.message_id == invalid_input for call in flow.session.calls)
    absent_input = await flow.feed(content="99999")
    assert any(isinstance(call, DeleteMessage) and call.message_id == absent_input for call in flow.session.calls)
    worker.assert_not_awaited()
    valid_input = await flow.feed(content="789")
    assert any(isinstance(call, DeleteMessage) and call.message_id == valid_input for call in flow.session.calls)
    await asyncio.sleep(0)
    worker.assert_awaited_once()
    assert worker.await_args.args == (flow.bot, 1001, 456, 789)
    progress = worker.await_args.kwargs["progress"]
    panel = next(call for call in reversed(flow.session.calls) if isinstance(call, EditMessageText))
    assert "Подготавливаю дамп" in panel.text
    panel_id = panel.message_id
    await progress("<b>Отправляю ZIP</b>")
    assert flow.session.calls[-1].message_id == panel_id
    if navigate:
        await flow.feed(callback="panel:home", panel_id=panel_id)
        count = len(flow.session.calls)
        await progress("<b>Дамп отправлен</b>", done=True)
        assert len(flow.session.calls) == count
    else:
        await progress("<b>Дамп отправлен</b>", done=True)
        assert flow.session.calls[-1].text == "<b>Дамп отправлен</b>"
        assert flow.session.calls[-1].message_id == panel_id
        assert (await flow.state().get_data())["dump_operation"] is None


@pytest.mark.asyncio
async def test_all_chats_dump_button_starts_background_export_without_id_prompt(setup_flow, monkeypatch):
    from core.personal_crypto import create_key_bundle
    from callbacks import backups as callback
    flow = setup_flow
    await flow.keys.install(1001, create_key_bundle(1001, "Личныйсекрет1001"))
    worker = AsyncMock()
    monkeypatch.setattr(flow.backups, "_dump", worker)
    await flow.feed(callback=callback.MENU)
    panel = next(call for call in reversed(flow.session.calls) if isinstance(call, EditMessageText))
    assert callback.DUMP_ALL in {button.callback_data for row in panel.reply_markup.inline_keyboard for button in row}
    downloads = [button for row in panel.reply_markup.inline_keyboard for button in row if button.url]
    assert len(downloads) == 1
    assert downloads[0].text == "Скачать просмотрщик · Windows"
    from core.versioning import get_local_version
    from core.viewer_distribution import windows_archive
    version = get_local_version()
    assert downloads[0].url.endswith(f"/releases/download/v{version}/{windows_archive(version)}")
    await flow.feed(callback=callback.DUMP_ALL, panel_id=panel.message_id)
    await asyncio.sleep(0)
    worker.assert_awaited_once()
    assert worker.await_args.args == (flow.bot, 1001, None, None)
    assert await flow.state().get_state() is None
    panel = next(call for call in reversed(flow.session.calls) if isinstance(call, EditMessageText))
    assert "Подготавливаю дамп всех чатов" in panel.text


@pytest.mark.asyncio
async def test_backup_import_deletes_secret_before_background_work_and_keeps_it_out_of_fsm(setup_flow, monkeypatch):
    from states.backups import IMPORT_FILES, IMPORT_SECRET
    flow = setup_flow
    identity = "a" * 32
    monkeypatch.setattr(flow.backups.uploads, "collect_parts", lambda *args: ["synthetic"])
    await flow.feed(callback="backup:import")  # A fresh installation can restore before setting up a new key.
    assert await flow.state().get_state() == IMPORT_FILES
    await flow.state().update_data(backup_identity=identity, backup_total=1)
    await flow.feed(callback="backup:restore")
    assert await flow.state().get_state() == IMPORT_SECRET
    async def restore(*args):
        assert any(isinstance(call, DeleteMessage) for call in flow.session.calls)
        assert "СекретБекапа123" not in str(await flow.state().get_data())
    worker = AsyncMock(side_effect=restore)
    monkeypatch.setattr(flow.backups, "_restore", worker)
    await flow.feed(content="СекретБекапа123")
    await asyncio.sleep(0)
    worker.assert_awaited_once()
    assert await flow.state().get_state() is None


class OfflineSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.messages = {}

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        raise AssertionError("No media in secret setup")
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, CreateForumTopic):
            return ForumTopic(message_thread_id=1000 + len(self.calls), name=method.name, icon_color=0)
        if isinstance(method, DeleteMessage):
            self.messages.pop((int(method.chat_id), method.message_id), None)
            return True
        if isinstance(method, AnswerCallbackQuery):
            return True
        assert isinstance(method, (SendMessage, EditMessageText, SendPhoto, EditMessageMedia, SendDocument))
        identity = (int(method.chat_id), getattr(method, "message_id", None) or len(self.calls))
        previous = self.messages.get(identity)
        if isinstance(method, EditMessageText) and previous is not None and isinstance(previous.reply_markup, ReplyKeyboardRemove):
            raise TelegramBadRequest(method=method, message="Bad Request: message can't be edited")
        if isinstance(method, EditMessageText) and isinstance(previous, (SendPhoto, EditMessageMedia)):
            raise TelegramBadRequest(method=method, message="Bad Request: there is no text in the message to edit")
        self.messages[identity] = method
        payload = {"message_id": identity[1], "date": 1,
            "chat": {"id": int(method.chat_id), "type": "private"},
            "from_user": {"id": bot.id, "is_bot": True, "first_name": "Offline bot"}}
        if getattr(method, "message_thread_id", None) is not None:
            payload["message_thread_id"] = method.message_thread_id
        if isinstance(method, SendDocument):
            payload.update(caption=method.caption, document={"file_id": "synthetic-log", "file_unique_id": "synthetic-log"})
        elif isinstance(method, (SendPhoto, EditMessageMedia)):
            payload.update(caption=method.media.caption if isinstance(method, EditMessageMedia) else method.caption,
                           photo=[{"file_id": "synthetic-chart", "file_unique_id": "synthetic-chart", "width": 1120, "height": 1110}])
        else:
            payload["text"] = method.text
        return Message.model_validate(payload).as_(bot)


@pytest_asyncio.fixture
async def setup_flow(db_main, offline_module, monkeypatch):
    repository = AdminsRepository(db_main.get_session_factory, [1001])
    monkeypatch.setattr(db_main, "admins_repository", repository)
    loader = ModuleType("loader")
    loader.router = Router()
    from core.session_manager import SessionManager
    loader.session_manager = SessionManager()
    loader.bot = AsyncMock()
    monkeypatch.setitem(sys.modules, "loader", loader)
    monkeypatch.setitem(sys.modules, "utils.others", SimpleNamespace(close_state_pyrogram_client=AsyncMock(),
                                                                 not_warning_delete_message=AsyncMock()))
    admission = offline_module("middlewares/admin_access.py")
    admission.is_admin = repository.is_admin
    profile = offline_module("middlewares/update_user.py")
    writes = AsyncMock(side_effect=db_main.update_user)
    profile.update_user = writes
    handled = []

    @loader.router.message()
    async def ordinary_handler(message):
        handled.append(message.text)

    keys = PersonalKeyRepository(db_main.get_session_factory)
    menu = offline_module("handlers/admin/admin_menu_handler.py")
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
    app_menu = offline_module("handlers/admin/apps_manager/apps_menu_handler.py")
    app_menu.get_app_tg_user_id = db_main.get_app_tg_user_id
    app_menu.get_account_counts_by_apps = db_main.get_account_counts_by_apps
    editor = offline_module("handlers/admin/panel/account_edit_handler.py")
    for name in ("get_account_uuid", "get_app_tg_uuid", "get_user_timezone_offset", "get_account_health_events",
                 "get_account_user_id", "get_app_tg_user_id", "get_user_names_by_ids", "update_account_uuid",
                 "add_account_health_event"):
        setattr(editor, name, getattr(db_main, name))
    editor.is_session_running = AsyncMock(return_value=False)
    deleter = offline_module("handlers/admin/panel/account_del_handler.py")
    deleter.request_delete_warning = ownership.request_delete_warning
    accounts = offline_module("handlers/admin/panel/accounts_menu_handler.py")
    for name in ("get_account_user_id", "get_app_tg_user_id", "get_user_names_by_ids"):
        setattr(accounts, name, getattr(db_main, name))
    settings = offline_module("handlers/admin/settings/setting_menu_handler.py")
    backups = offline_module("handlers/admin/backups.py")
    backups.get_configured_admin_ids = db_main.get_configured_admin_ids
    monkeypatch.setattr(backups, "_busy", set())
    for name in ("get_accounts_overview", "get_archive_statistics", "get_account_all", "get_runtime_health", "get_configured_admin_ids", "get_admin_health_events", "get_all_health_events",
                 "get_latest_admin_health_event", "get_user_auto_update_enabled", "get_user_gemini_proxy_config",
                 "get_user_timezone_offset", "get_version_state_cache", "set_version_state_cache"):
        setattr(settings, name, getattr(db_main, name))
    settings._fetch_latest_version = AsyncMock(return_value="2.0.3")
    admins = offline_module("handlers/admin/admins_handler.py")
    for name in ("get_admin_grants", "get_admin_ids", "get_configured_admin_ids", "get_user",
                 "grant_admin", "is_admin", "revoke_admin"):
        setattr(admins, name, getattr(db_main, name))
    search = offline_module("handlers/admin/panel/chat_history_handler.py")
    for name in ("find_user_ids_by_username", "get_account_all", "get_chat_history_events",
                 "get_chat_history_events_by_chat_ids", "get_dump_chat_user", "get_user", "get_user_timezone_offset"):
        setattr(search, name, getattr(db_main, name))
    # Account filters resolve this module lazily; use real owner-scoped queries.
    monkeypatch.setitem(sys.modules, "db.main", db_main)
    dispatcher = Dispatcher(events_isolation=SimpleEventIsolation())
    dispatcher.message.middleware(profile.UpdateUserMiddleware())
    dispatcher.update.outer_middleware(admission.AdminAccessMiddleware())
    dispatcher.update.outer_middleware(AuthSessionCleanupMiddleware())
    dispatcher.update.outer_middleware(PersonalSecretMiddleware(keys, account_access.can_use_secret))
    dispatcher.include_router(menu.router)
    dispatcher.include_router(ownership.router)
    dispatcher.include_router(apps.router)
    dispatcher.include_router(app_menu.router)
    dispatcher.include_router(editor.router)
    dispatcher.include_router(deleter.router)
    dispatcher.include_routers(accounts.router, settings.router, admins.router, search.router)
    dispatcher.include_router(backups.router)
    dispatcher.include_router(loader.router)
    session = OfflineSession()
    bot = Bot("123456:offline_test_token", session=session)
    monkeypatch.setattr(bot, "get_me", AsyncMock(return_value=SimpleNamespace(has_topics_enabled=False)))
    serial = 0

    async def feed(user_id=1001, *, content=None, callback=None, inaccessible=False, panel_id=None, thread_id=None):
        nonlocal serial
        serial += 1
        user = {"id": user_id, "is_bot": False, "first_name": "Offline admin"}
        message = {"message_id": serial, "date": 0 if inaccessible else 1,
                   "chat": {"id": user_id, "type": "private"}, "from_user": user, "text": content or "old menu"}
        if thread_id is not None:
            message["message_thread_id"] = thread_id
        if callback is not None:
            message["message_id"] = panel_id if panel_id is not None else serial
            message["from_user"] = {"id": bot.id, "is_bot": True, "first_name": "Offline bot"}
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
                              db=db_main, ownership=ownership, search=search, settings=settings, editor=editor, bot=bot,
                              backups=backups)
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
    first_prompt = (await flow.state().get_data())["secret_prompt_id"]
    first = await flow.feed(content="Рыжий кот 527")
    assert await flow.state().get_state() == SECRET_CONFIRM
    assert await flow.keys.get(1001) is None
    assert "рыжийкот527" not in str(await flow.state().get_data())
    second_prompt = (await flow.state().get_data())["secret_prompt_id"]
    second = await flow.feed(content="рыжийКОТ527")
    assert await flow.keys.get(1001) is not None
    assert {call.message_id for call in flow.session.calls if isinstance(call, DeleteMessage)} == {first, second, first_prompt, second_prompt}
    assert "Рыжий кот 527" not in str(flow.session.calls)
    flow.writes.assert_not_awaited()
    assert flow.handled == []
    await flow.feed(content="/start")
    assert flow.handled == []
    assert flow.session.calls[-1].reply_markup.inline_keyboard
    flow.writes.assert_awaited_once()
    await flow.feed(callback=SETUP_CALLBACK, inaccessible=True)
    assert isinstance(flow.session.calls[-1], AnswerCallbackQuery)
    replacement = next(call for call in reversed(flow.session.calls) if isinstance(call, SendMessage))
    assert replacement.reply_markup.inline_keyboard


@pytest.mark.asyncio
@pytest.mark.parametrize("full", [False, True])
async def test_editor_delete_buttons_keep_mode_until_explicit_confirmation(setup_flow, monkeypatch, full):
    from unittest.mock import Mock
    from sqlalchemy import select
    from core.personal_crypto import create_key_bundle
    from db.account_operation_models import AccountOperation
    from db.repositories.account_operations_repo import AccountOperationsRepository
    from callbacks.account_ownership import OwnAccount
    from data.texts import account_ownership as text

    flow = setup_flow
    await flow.keys.install(1001, create_key_bundle(1001, "Личныйсекрет527"))
    await flow.db.create_app_tg(1001, 12345, "synthetic-api-hash", "owner")
    profile = (await flow.db.get_app_tg_user_id(1001))[0][0]
    account = await flow.db.create_account_tg(1001, 2002, profile.uuid, "79000000001")
    operations = AccountOperationsRepository(flow.db.get_session_factory)
    monkeypatch.setattr(flow.ownership, "repository", operations)
    schedule = Mock()
    monkeypatch.setattr(flow.ownership, "schedule_deletion", schedule)
    await flow.feed(callback=f"acc:{'purge' if full else 'del'}:{account.uuid}")
    schedule.assert_not_called()
    async with flow.db.get_session_factory()() as session:
        operation = await session.scalar(select(AccountOperation))
    assert operation.kind == ("delete_full" if full else "delete")
    assert operation.status == "confirm_delete"
    panel = next(call for call in reversed(flow.session.calls) if isinstance(call, EditMessageText))
    expected = text.DELETE_FULL_WARNING if full else text.DELETE_WARNING
    assert panel.text == expected.format(account_id=2002)
    await flow.feed(callback=OwnAccount(action="erase", token=operation.uuid.hex).pack())
    schedule.assert_called_once()
    assert schedule.call_args.args[0].kind == operation.kind
    assert (await operations.get(operation.uuid, 1001)).status == "deleting"


@pytest.mark.asyncio
async def test_connected_user_needs_admin_grant_to_create_own_profile(setup_flow):
    from core.personal_crypto import create_key_bundle
    import time

    flow = setup_flow
    await flow.db.create_app_tg(1001, 12345, "foreign-synthetic-hash", "owner")
    app = (await flow.db.get_app_tg_user_id(1001))[0][0]
    await flow.db.create_account_tg(1001, 2002, app.uuid, "79000000001")
    await flow.keys.install(2002, create_key_bundle(2002, "Личныйсекрет2002"))
    await flow.state(2002).update_data(personal_verified_until=int(time.time()) + 600)
    for content in ("/start", "Мой аккаунт", "🔑 API-профили"):
        await flow.feed(2002, content=content)
    await flow.feed(2002, callback="apps_admin_menu_add")
    assert not flow.session.calls and not flow.handled
    assert (await flow.db.get_app_tg_user_id(2002))[1] == 0
    await flow.admins.grant(1001, 2002)
    await flow.state(2002).update_data(personal_verified_until=int(time.time()) + 600)
    await flow.feed(2002, callback="apps_admin_menu_add")
    await flow.feed(2002, content="23456")
    await flow.feed(2002, content="own-synthetic-hash")
    await flow.feed(2002, content="Моё приложение")
    await flow.feed(2002, callback="agree")
    profiles, count = await flow.db.get_app_tg_user_id(2002)
    assert count == 1 and profiles[0].api_hash == "own-synthetic-hash"
    assert (await flow.db.get_app_tg_user_id(1001))[1] == 1
    assert await flow.admins.is_admin(2002)
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
async def test_admin_self_view_hides_foreign_profile_and_deletion_survives_fsm_reset(setup_flow):
    from callbacks.account_ownership import OwnAccount
    from db.repositories.account_operations_repo import AccountOperationsRepository

    flow = setup_flow
    await flow.admins.grant(1001, 2002)
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
    warning = next(call for call in reversed(flow.session.calls) if isinstance(call, EditMessageText))
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


@pytest.mark.asyncio
@pytest.mark.parametrize("self_is_admin", [False, True])
async def test_foreign_profile_is_hidden_from_connected_account_even_with_admin_role(setup_flow, self_is_admin):
    from callbacks.account_ownership import OwnAccount
    from core.personal_crypto import create_key_bundle

    flow = setup_flow
    if self_is_admin:
        await flow.admins.grant(1001, 2002)
    await flow.db.create_app_tg(1001, 654321, "foreign-api-secret", "foreign-profile")
    await flow.db.create_app_tg(2002, 765432, "own-api-secret", "own-profile")
    foreign = (await flow.db.get_app_tg_user_id(1001))[0][0]
    account = await flow.db.create_account_tg(1001, 2002, foreign.uuid, "79000000001")
    await flow.keys.install(1001, create_key_bundle(1001, "Секретвладельца714"))
    await flow.keys.install(2002, create_key_bundle(2002, "Секретаккаунта823"))

    def emitted_since(index):
        return str([call.model_dump() for call in flow.session.calls[index:]])

    start = len(flow.session.calls)
    await flow.feed(2002, content=flow.ownership.text.MENU)
    await flow.feed(2002, callback=OwnAccount(action="detail", token=account.uuid.hex).pack())
    if not self_is_admin:
        await flow.feed(2002, callback="apps_admin_menu:1")
        await flow.feed(2002, callback=OwnAccount(action="profiles").pack())
        assert len(flow.session.calls) == start
        assert flow.handled == []
        return
    card = next(call for call in reversed(flow.session.calls) if isinstance(call, EditMessageText))
    actions = {OwnAccount.unpack(button.callback_data).action for row in card.reply_markup.inline_keyboard for button in row
               if button.callback_data.startswith("own:")}
    assert actions == {"profiles", "delete", "home"}
    await flow.feed(2002, callback="apps_admin_menu:1")
    await flow.feed(2002, callback=OwnAccount(action="profiles").pack())
    assert "765432" in emitted_since(start)  # Own API profile remains selectable.
    selector = next(call for call in reversed(flow.session.calls) if isinstance(call, EditMessageText))
    assert selector.reply_markup.inline_keyboard[-1][0].callback_data == OwnAccount(
        action="detail", token=str(account.uuid)).pack()
    # Stale/forged manager buttons must neither reveal credentials nor alter state.
    await flow.feed(2002, callback=f"acc:e:{account.uuid}")
    await flow.feed(2002, callback=f"acc:tn:{account.uuid}")
    output = emitted_since(start)
    for value in ("654321", "foreign-api-secret", "foreign-profile", "79000000001", str(foreign.uuid)):
        assert value not in output
    assert (await flow.db.get_account_uuid(account.uuid, 1001)).alert_new_chat == account.alert_new_chat
    if self_is_admin:
        assert await flow.db.get_app_tg_uuid(foreign.uuid, 2002) is None
        assert (await flow.db.get_app_tg_user_id(2002))[1] == 1
    start = len(flow.session.calls)
    await flow.feed(1001, callback=f"acc:e:{account.uuid}")
    assert "654321" in emitted_since(start) and "foreign-api-secret" in emitted_since(start)


@pytest.mark.asyncio
async def test_profile_created_in_bot_is_visible_only_to_creator_on_open_and_refresh(setup_flow):
    from core.personal_crypto import create_key_bundle
    import data.text as texts
    import time

    flow = setup_flow
    await flow.admins.grant(1001, 2002)
    for user_id in (1001, 2002):
        await flow.keys.install(user_id, create_key_bundle(user_id, f"Личныйсекрет{user_id}"))
    await flow.state(2002).update_data(personal_verified_until=int(time.time()) + 600)
    await flow.feed(2002, callback="apps_admin_menu_add")
    await flow.feed(2002, content="765432")
    await flow.feed(2002, content="private-created-through-bot")
    await flow.feed(2002, content="profile-of-2002")
    await flow.feed(2002, callback="agree")
    profiles, total = await flow.db.get_app_tg_user_id(2002)
    assert total == 1 and profiles[0].user_id == 2002
    assert (await flow.db.get_app_tg_user_id(1001))[1] == 0

    start = len(flow.session.calls)
    await flow.feed(1001, content=texts.APP_TG_USER_KEYBOARD[0])
    await flow.feed(1001, callback="apps_admin_menu:1")
    responses = [call for call in flow.session.calls[start:] if isinstance(call, (SendMessage, EditMessageText))]
    assert len(responses) == 2
    for response in responses:
        buttons = [button for row in response.reply_markup.inline_keyboard for button in row]
        assert not any((button.callback_data or "").startswith("account_admin_menu_add:") for button in buttons)
        assert "765432" not in str(response.model_dump())
        assert "profile-of-2002" not in str(response.model_dump())
    start = len(flow.session.calls)
    await flow.feed(2002, content=texts.APP_TG_USER_KEYBOARD[0])
    assert "765432" in str([call.model_dump() for call in flow.session.calls[start:]])


@pytest.mark.asyncio
async def test_only_start_opens_panel_and_other_commands_do_not_enter_wizards(setup_flow):
    from callbacks.personal_secret import CANCEL_CALLBACK
    from core.personal_crypto import create_key_bundle

    flow = setup_flow
    await flow.keys.install(1001, create_key_bundle(1001, "Личныйсекрет1001"))
    await flow.feed(content="/start")
    labels = {button.text for row in flow.session.calls[-1].reply_markup.inline_keyboard for button in row}
    assert {"👥 Администраторы", "⚙️ Настройки", "🔑 API-профили", "Мой аккаунт"} <= labels
    assert len(flow.session.calls[-1].reply_markup.inline_keyboard) == 4
    start = len(flow.session.calls)
    writes = flow.writes.await_count
    for command in ("/admins", "/myaccount", "/secret", "/cancel", "/chat_history 123", "/startfoo"):
        await flow.feed(content=command)
    assert len(flow.session.calls) == start and flow.writes.await_count == writes
    assert not flow.handled

    await flow.feed(callback=SETUP_CALLBACK)
    controls = next(call for call in reversed(flow.session.calls) if isinstance(call, EditMessageText))
    assert controls.reply_markup.inline_keyboard[0][0].callback_data == CANCEL_CALLBACK
    await flow.feed(callback=CANCEL_CALLBACK)
    assert await flow.state().get_state() is None
    await flow.feed(callback="panel:home")
    assert next(call for call in reversed(flow.session.calls) if isinstance(call, EditMessageText)).reply_markup.inline_keyboard


@pytest.mark.asyncio
async def test_start_sends_one_inline_menu_and_removes_legacy_keyboard_notice(setup_flow):
    from core.personal_crypto import create_key_bundle
    from data.texts.common import START_MESSAGE_TEXT, START_PANEL_OPENING_TEXT

    flow = setup_flow
    await flow.keys.install(1001, create_key_bundle(1001, "Личныйсекрет1001"))
    await flow.feed(content="/start")
    panels = [(identity, method) for identity, method in flow.session.messages.items()
              if method.text == START_MESSAGE_TEXT]
    assert len(panels) == 1 and panels[0][1].reply_markup.inline_keyboard
    assert not any(method.text == START_PANEL_OPENING_TEXT for method in flow.session.messages.values())
    panel_id = panels[0][0][1]
    assert (await flow.state().get_data())["panel_message_id"] == panel_id
    assert not any(isinstance(call, EditMessageText) for call in flow.session.calls)

    await flow.feed(content="/start")
    new_panel_id = (await flow.state().get_data())["panel_message_id"]
    assert new_panel_id != panel_id
    assert (1001, panel_id) not in flow.session.messages
    assert sum(isinstance(call, SendMessage) and call.text == START_MESSAGE_TEXT for call in flow.session.calls) == 2
    # An immediate third /start must also produce visible feedback.
    await flow.feed(content="/start")
    assert sum(isinstance(call, SendMessage) and call.text == START_MESSAGE_TEXT for call in flow.session.calls) == 3


@pytest.mark.asyncio
async def test_start_still_opens_inline_menu_when_legacy_notice_cannot_be_deleted(setup_flow, monkeypatch):
    from core.personal_crypto import create_key_bundle
    from data.texts.common import START_MESSAGE_TEXT

    flow = setup_flow
    await flow.keys.install(1001, create_key_bundle(1001, "Личныйсекрет1001"))
    original = flow.session.make_request

    async def cannot_delete(bot, method, timeout=None):
        if isinstance(method, DeleteMessage):
            raise TelegramBadRequest(method=method, message="Bad Request: message can't be deleted")
        return await original(bot, method, timeout)

    monkeypatch.setattr(flow.session, "make_request", cannot_delete)
    await flow.feed(content="/start")
    menus = [method for method in flow.session.messages.values() if method.text == START_MESSAGE_TEXT]
    assert len(menus) == 1 and menus[0].reply_markup.inline_keyboard


@pytest.mark.asyncio
async def test_secret_settings_show_status_without_requesting_secret(setup_flow):
    import time
    from callbacks.personal_secret import STATUS_CALLBACK
    from core.personal_crypto import create_key_bundle
    from data.texts import personal_secret as text
    flow = setup_flow
    await flow.keys.install(1001, create_key_bundle(1001, "Личныйсекрет1001"))
    until = int(time.time()) + 600
    await flow.state().update_data(personal_verified_until=until)
    await flow.feed(callback=STATUS_CALLBACK)
    assert await flow.state().get_state() is None
    assert (await flow.state().get_data())["personal_verified_until"] == until
    panel = next(call for call in reversed(flow.session.calls) if isinstance(call, EditMessageText))
    assert panel.text == text.STATUS_CONFIGURED
    assert not any(isinstance(call, SendMessage) and call.text == text.INPUT_PROMPT for call in flow.session.calls)


@pytest.mark.asyncio
async def test_start_and_home_route_to_menu_topic_and_navigation_stays_there(setup_flow):
    from core.personal_crypto import create_key_bundle
    from db.repositories.topics_repo import TopicsRepository
    flow = setup_flow
    await flow.keys.install(1001, create_key_bundle(1001, "Личныйсекрет1001"))
    flow.bot.get_me.return_value.has_topics_enabled = True
    await flow.feed(content="/start")
    thread = await TopicsRepository(flow.db.get_session_factory).get(flow.bot.id, 1001, "menu")
    panel = next(call for call in reversed(flow.session.calls) if isinstance(call, SendMessage))
    assert thread is not None and panel.message_thread_id == thread
    # Home from a legacy/root panel opens the dedicated menu destination.
    await flow.feed(callback="panel:home", panel_id=99)
    panel_id = (await flow.state().get_data())["panel_message_id"]
    assert flow.session.messages[(1001, panel_id)].message_thread_id == thread
    count = sum(isinstance(call, SendMessage) for call in flow.session.calls)
    await flow.feed(callback="panel:home", panel_id=panel_id, thread_id=thread)
    assert sum(isinstance(call, SendMessage) for call in flow.session.calls) == count


@pytest.mark.asyncio
async def test_stats_button_is_acknowledged_before_collecting_data(setup_flow, monkeypatch):
    from core.personal_crypto import create_key_bundle
    flow = setup_flow
    await flow.keys.install(1001, create_key_bundle(1001, "Личныйсекрет1001"))
    async def inspect(*args, **kwargs):
        assert isinstance(flow.session.calls[-1], AnswerCallbackQuery)
    collect = AsyncMock(side_effect=inspect)
    monkeypatch.setattr(flow.settings, "_send_stats", collect)
    await flow.feed(callback="panel:stats:own")
    collect.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("topics", [False, True])
async def test_latest_log_button_streams_to_log_topic_and_denies_granted_admin(setup_flow, monkeypatch, tmp_path, topics):
    from core.personal_crypto import create_key_bundle
    from aiogram.types import FSInputFile
    flow = setup_flow
    flow.bot.get_me.return_value.has_topics_enabled = topics
    path = tmp_path / "latest.log"
    path.write_text("синтетический лог", encoding="utf-8")
    monkeypatch.setattr(flow.settings, "latest_log_file", lambda: path)
    await flow.admins.grant(1001, 2002)
    for owner in (1001, 2002):
        await flow.keys.install(owner, create_key_bundle(owner, f"Личныйсекрет{owner}"))
    await flow.feed(callback="panel:settings")
    assert "set:logs:last" in str(next(call for call in reversed(flow.session.calls) if isinstance(call, EditMessageText)).reply_markup)
    await flow.feed(callback="set:logs:last", thread_id=77 if topics else None)
    document = flow.session.calls[-1]
    assert isinstance(document, SendDocument) and isinstance(document.document, FSInputFile)
    assert document.document.path == path and document.document.filename == "latest.txt"
    if topics:
        from db.repositories.topics_repo import TopicsRepository
        thread_id = await TopicsRepository(flow.db.get_session_factory).get(flow.bot.id, 1001, "logs")
        assert document.message_thread_id == thread_id and thread_id != 77
        assert any(isinstance(call, CreateForumTopic) and call.name == "Логи" for call in flow.session.calls)
        await flow.feed(callback="set:logs:last", thread_id=77)
        assert flow.session.calls[-1].message_thread_id == thread_id
        assert sum(isinstance(call, CreateForumTopic) for call in flow.session.calls) == 1
    else:
        assert document.message_thread_id is None
        assert not any(isinstance(call, CreateForumTopic) for call in flow.session.calls)
    await flow.feed(2002, callback="panel:settings")
    assert "set:logs:last" not in str(next(call for call in reversed(flow.session.calls) if isinstance(call, EditMessageText)).reply_markup)
    start = len(flow.session.calls)
    await flow.feed(2002, callback="set:logs:last")
    assert not any(isinstance(call, SendDocument) for call in flow.session.calls[start:])
    assert not any(isinstance(call, CreateForumTopic) for call in flow.session.calls[start:])
    assert path.read_text(encoding="utf-8") == "синтетический лог"


@pytest.mark.asyncio
async def test_stats_are_one_chart_panel_and_home_removes_the_old_photo(setup_flow, monkeypatch):
    from core.personal_crypto import create_key_bundle
    flow = setup_flow
    await flow.keys.install(1001, create_key_bundle(1001, "Личныйсекрет1001"))
    await flow.feed(content="/start")
    panel_id = (await flow.state().get_data())["panel_message_id"]
    for callback in ("panel:stats:own", "panel:stats:all"):
        await flow.feed(callback=callback, panel_id=panel_id)
        chart = next(call for call in reversed(flow.session.calls) if isinstance(call, EditMessageMedia))
        assert chart.message_id == panel_id
        assert len(chart.media.caption) < 1024 and "0.0%" not in chart.media.caption
        assert "Чатов:" in chart.media.caption and "Файлов:" in chart.media.caption
        assert "История проверена:" in chart.media.caption and "всего ≈" in chart.media.caption
        assert chart.media.media.data.startswith(b"\x89PNG")
    await flow.feed(callback="panel:home", panel_id=panel_id)
    replacement = (await flow.state().get_data())["panel_message_id"]
    assert replacement != panel_id and (1001, panel_id) not in flow.session.messages
    assert len(flow.session.messages) == 1
    await flow.feed(content="/start")
    previous = replacement
    replacement = (await flow.state().get_data())["panel_message_id"]
    assert replacement != previous and (1001, previous) not in flow.session.messages
    # Telegram captions have a hard limit, including when counters and errors grow.
    monkeypatch.setattr(flow.settings, "get_accounts_overview", AsyncMock(return_value={
        name: 9_000_000_000_000_000_000 for name in ("own_active", "own_total", "all_active", "all_total")}))
    monkeypatch.setattr(flow.settings, "get_archive_statistics", AsyncMock(return_value={
        name: 9_000_000_000_000_000_000 for name in ("messages", "edited", "revisions", "deleted", "missing",
            "media_stored", "media_pending", "media_failed", "history_reached", "history_chats")}))
    monkeypatch.setattr(flow.settings, "get_admin_health_events", AsyncMock(return_value=[
        SimpleNamespace(date=1, reason="synthetic" * 30, status=0), SimpleNamespace(date=2, reason="synthetic" * 30, status=0)]))
    await flow.feed(callback="panel:stats:own", panel_id=replacement)
    assert len(next(call for call in reversed(flow.session.calls) if isinstance(call, EditMessageMedia)).media.caption) < 1024


@pytest.mark.asyncio
async def test_manual_check_of_failed_runtime_records_failure_without_deleting_account(setup_flow, monkeypatch):
    from core.personal_crypto import create_key_bundle
    from core.session_manager import SessionUnavailable
    flow = setup_flow
    await flow.keys.install(1001, create_key_bundle(1001, "Личныйсекрет1001"))
    await flow.db.create_app_tg(1001, 12345, "synthetic", "app")
    app = (await flow.db.get_app_tg_user_id(1001))[0][0]
    account = await flow.db.create_account_tg(1001, 2002, app.uuid, "79000000001")
    monkeypatch.setattr(flow.editor, "get_client_by_number", AsyncMock(return_value=SimpleNamespace(get_me=AsyncMock())))
    monkeypatch.setattr(flow.editor, "run_client_operation", AsyncMock(side_effect=SessionUnavailable()))
    await flow.feed(callback=f"acc:chk:{account.uuid}")
    events = await flow.db.get_account_health_events(account.uuid, 0)
    assert len(events) == 1 and events[0].status == 0 and events[0].reason == "not_running"
    assert (await flow.db.get_account_uuid(account.uuid, 1001)).is_active == 1


@pytest.mark.asyncio
async def test_inline_sections_and_text_wizards_edit_same_panel_after_state_reset(setup_flow, monkeypatch):
    import time
    from callbacks.account_ownership import HOME_CALLBACK
    from core.personal_crypto import create_key_bundle

    flow = setup_flow
    await flow.keys.install(1001, create_key_bundle(1001, "Личныйсекрет1001"))
    await flow.feed(content="/start")
    panel_id = (await flow.state().get_data())["panel_message_id"]
    first = len(flow.session.calls)
    for callback in ("panel:settings", "set:tz:open", "set:back", "panel:home", "panel:accounts",
                     "panel:apps", "panel:home", HOME_CALLBACK, "panel:home", "adm:list:0",
                      "panel:home", "panel:search"):
        await flow.state().clear()  # Navigation survives loss of a short-lived dialog.
        before = len(flow.session.calls)
        await flow.feed(callback=callback, panel_id=panel_id)
        assert any(isinstance(call, EditMessageText) for call in flow.session.calls[before:]), callback
    await flow.feed(content="777")
    await flow.feed(callback="panel:home", panel_id=panel_id)
    await flow.feed(callback="adm:add", panel_id=panel_id)
    await flow.feed(content="2002")
    await flow.feed(callback="panel:home", panel_id=panel_id)
    await flow.state().update_data(personal_verified_until=int(time.time()) + 600)
    await flow.feed(callback="apps_admin_menu_add", panel_id=panel_id)
    for content in ("23456", "synthetic-inline-hash", "Мой API-профиль"):
        await flow.feed(content=content)
    await flow.feed(callback="agree", panel_id=panel_id)
    assert (await flow.db.get_app_tg_user_id(1001))[1] == 1
    await flow.feed(callback="panel:search", panel_id=panel_id)
    source = SimpleNamespace(bot=flow.bot, chat=SimpleNamespace(id=1001))
    await flow.search._send_chunked(source, "\n".join(f"Событие {i}" for i in range(100)),
                                    chunk_size=300, state=flow.state())
    await flow.feed(callback="history:page:1", panel_id=panel_id)
    assert "history:page:0" in str(flow.session.calls[-2].reply_markup)
    await flow.state().clear()
    await flow.feed(callback="history:page:0", panel_id=panel_id)
    assert flow.session.calls[-2].text == flow.search.constant_text.CHAT_HISTORY_SEARCH_PROMPT_TEXT

    import core.auth_sessions as auth
    import middlewares.auth_session_cleanup as cleanup
    registry = auth.TemporaryClients()
    monkeypatch.setattr(cleanup, "auth_clients", registry)
    monkeypatch.setattr(auth, "_remove_files", AsyncMock())
    client = SimpleNamespace(is_connected=True, is_initialized=False, disconnect=AsyncMock())
    registry.register(client, "data/session/_auth_1001_79000000001_" + "f" * 32)
    await flow.state().set_state("AdminStates:account_add_code")
    await flow.state().update_data(app_temp=client)
    await flow.feed(callback="panel:home", panel_id=panel_id)
    client.disconnect.assert_awaited_once()
    assert not registry.contains(client) and await flow.state().get_state() is None
    emitted = flow.session.calls[first:]
    assert not any(isinstance(call, SendMessage) for call in emitted)
    edits = [call for call in emitted if isinstance(call, EditMessageText)]
    assert all(call.message_id == panel_id for call in edits)
    assert all(any(button.callback_data == "panel:home" for row in call.reply_markup.inline_keyboard
                   for button in row) for call in edits if "<b>WatchTowerBot</b>" not in call.text)


@pytest.mark.asyncio
async def test_navigation_uses_root_siblings_and_real_parent_buttons(setup_flow):
    from core.personal_crypto import create_key_bundle
    from data.texts.common import START_MESSAGE_TEXT

    flow = setup_flow
    await flow.admins.grant(1001, 2002)
    await flow.keys.install(1001, create_key_bundle(1001, "Личныйсекрет1001"))
    await flow.feed(content="/start")
    panel_id = (await flow.state().get_data())["panel_message_id"]

    def screen():
        return next(call for call in reversed(flow.session.calls) if isinstance(call, (SendMessage, EditMessageText)))

    def payload(expected):
        return next(button.callback_data for row in screen().reply_markup.inline_keyboard for button in row
                    if button.callback_data == expected)

    await flow.feed(callback=payload("adm:list:0"), panel_id=panel_id)
    assert [button.callback_data for button in screen().reply_markup.inline_keyboard[-1]] == ["panel:home"]
    await flow.feed(callback=payload("adm:view:2002:0"), panel_id=panel_id)
    await flow.feed(callback=payload("adm:list:0"), panel_id=panel_id)
    assert screen().text.startswith("<b>Администраторы</b>")
    await flow.state().clear()  # No navigation history in FSM is required.
    await flow.feed(callback=payload("panel:home"), panel_id=panel_id)
    assert screen().text == START_MESSAGE_TEXT
    await flow.feed(callback=payload("panel:settings"), panel_id=panel_id)
    assert not any(button.callback_data.startswith("adm:") for row in screen().reply_markup.inline_keyboard for button in row)
    await flow.feed(callback=payload("set:tz:open"), panel_id=panel_id)
    await flow.feed(callback=payload("set:back"), panel_id=panel_id)
    assert screen().text.startswith("<b>Настройки</b>")
    assert [button.callback_data for button in screen().reply_markup.inline_keyboard[-1]] == ["panel:home"]
    await flow.feed(callback=payload("panel:home"), panel_id=panel_id)
    assert screen().text == START_MESSAGE_TEXT and screen().message_id == panel_id


@pytest.mark.asyncio
async def test_secret_verification_returns_to_profiles_without_repeating_verification(setup_flow):
    from core.personal_crypto import create_key_bundle
    from states.personal_secret import SECRET_VERIFY

    flow = setup_flow
    await flow.keys.install(1001, create_key_bundle(1001, "Личныйсекрет1001"))
    await flow.feed(content="/start")
    panel_id = (await flow.state().get_data())["panel_message_id"]
    await flow.feed(callback="panel:apps", panel_id=panel_id)
    await flow.feed(callback="apps_admin_menu_add", panel_id=panel_id)
    assert await flow.state().get_state() == SECRET_VERIFY
    await flow.feed(content="Личныйсекрет1001")
    result = next(call for call in reversed(flow.session.calls) if isinstance(call, EditMessageText))
    assert {button.callback_data for row in result.reply_markup.inline_keyboard for button in row} == {"panel:apps", "panel:home"}
    await flow.feed(callback="panel:apps", panel_id=panel_id)
    before = len(flow.session.calls)
    await flow.feed(callback="apps_admin_menu_add", panel_id=panel_id)
    assert await flow.state().get_state() == "AdminStates:apps_add_app_id"
    assert not any(isinstance(call, SendMessage) for call in flow.session.calls[before:])
