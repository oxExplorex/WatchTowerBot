from pathlib import Path
import subprocess
import sys
import textwrap


def test_real_loader_and_consumers_share_one_registry():
    probe = textwrap.dedent("""
        import asyncio
        import logging
        import sys
        import types
        from unittest.mock import AsyncMock, Mock

        import handlers.admin.personal_secret
        assert "loader" not in sys.modules
        assert "db.main" not in sys.modules

        config = types.ModuleType("data.config")
        config.TOKEN_BOT = "123456:offline_test_token"
        config.GEMINI_KEY = ""
        config.GEMINI_ACTION_DEBUG = False
        config.admin_id_list = []
        sys.modules["data.config"] = config
        logger = types.ModuleType("core.logging")
        logger.bot_logger = logging.getLogger("offline_bootstrap")
        logger.install_global_exception_hooks = lambda *args: None
        sys.modules["core.logging"] = logger
        database = types.ModuleType("db.main")

        def database_function(name):
            if name.startswith("__"):
                raise AttributeError(name)
            function = AsyncMock(name=name)
            setattr(database, name, function)
            return function

        database.__getattr__ = database_function
        sys.modules["db.main"] = database

        import loader
        import main
        import aiotask.telegram_parse_dialogs as parser
        import core.session_runtime as runtime
        from pyrogram import Client

        assert main.session_manager is loader.session_manager
        assert parser.session_manager is loader.session_manager

        async def check():
            from aiogram import Bot, Dispatcher
            from aiogram.client.session.base import BaseSession
            from aiogram.exceptions import TelegramBadRequest
            from aiogram.types import Message as BotMessage, Update, User as BotUser
            from aiogram.methods import GetMe, SendMessage

            class OfflineSession(BaseSession):
                def __init__(self):
                    super().__init__()
                    self.calls = []
                    self.fail = False
                async def close(self):
                    pass
                async def stream_content(self, *args, **kwargs):
                    raise AssertionError("No network in router test")
                    yield b""
                async def make_request(self, bot, method, timeout=None):
                    self.calls.append(method)
                    if self.fail:
                        raise TelegramBadRequest(method=method, message="synthetic-private-error")
                    if isinstance(method, GetMe):
                        return BotUser(id=bot.id, is_bot=True, first_name="Offline", has_topics_enabled=False)
                    if isinstance(method, SendMessage):
                        return BotMessage.model_validate({"message_id": 99, "date": 1,
                            "chat": {"id": int(method.chat_id), "type": "private"}, "text": method.text}).as_(bot)
                    return True

            session = OfflineSession()
            test_bot = Bot("123456:offline_test_token", session=session)
            real_dispatcher = Dispatcher()
            real_dispatcher.include_router(main.router)
            payload = {"update_id": 1, "message": {"message_id": 1, "date": 1,
                "chat": {"id": 1001, "type": "private"}, "text": "/start",
                "from_user": {"id": 1001, "first_name": "Offline", "is_bot": False}}}
            await real_dispatcher.feed_update(test_bot, Update.model_validate(payload))
            assert len(session.calls) == 4  # Keyboard reset, delete notice, topic capability, inline panel.
            session.fail = True
            await real_dispatcher.feed_update(test_bot, Update.model_validate(payload | {"update_id": 2}))
            assert len(session.calls) == 5  # Root error router handles a sibling's error.
            await real_dispatcher.storage.close()
            await test_bot.session.close()

            client = Client("offline", api_id=12345, api_hash="offline", in_memory=True)
            client.add_handler = Mock()
            client.stop = AsyncMock()
            loader.is_connected = lambda: True
            loader._get_apps_user = AsyncMock(return_value=[client])
            loader._build_gemini_system_instruction = AsyncMock(return_value="offline instruction")
            await loader.initialize_runtime_state()
            await loader.initialize_runtime_state()
            loader._get_apps_user.assert_awaited_once()
            assert loader.gemini_system_instruction == "offline instruction"
            clients = await loader.session_manager.get_snapshot()
            assert clients == [client]
            assert await runtime.get_client_by_number("offline") is client
            main._register_pyrogram_handlers(clients)
            assert client.add_handler.call_count == 6
            registrations = client.add_handler.call_args_list
            spoiler = next(call for call in registrations if getattr(call.args[0].callback, "__wrapped__", None) is main.file_spoiler_handler)
            archive = next(call for call in registrations if getattr(call.args[0].callback, "__wrapped__", None) is main.chat_presence_sync_handler)
            assert spoiler.kwargs["group"] != archive.kwargs["group"]
            # Exercise the actual SDK worker: a photo must reach both consumers,
            # not just appear twice in the registration list.
            from collections import OrderedDict
            from datetime import datetime, timezone
            from pyrogram.types import Message, Photo
            message = Message(id=12, has_media_spoiler=True,
                photo=Photo(file_id="offline", file_unique_id="offline", width=1,
                            height=1, file_size=1, date=datetime.now(timezone.utc)))
            class Packet:
                pts = 1
            async def parse_packet(*args):
                return message, main.MessageHandler
            groups = {}
            for registration in registrations:
                handler = registration.args[0]
                if isinstance(handler, main.MessageHandler):
                    handler.callback = AsyncMock()
                groups.setdefault(registration.kwargs["group"], []).append(handler)
            client.dispatcher.groups = OrderedDict(sorted(groups.items()))
            client.dispatcher.update_parsers = {Packet: parse_packet}
            await client.dispatcher.updates_queue.put((Packet(), {}, {}))
            await client.dispatcher.updates_queue.put(None)
            await client.dispatcher.handler_worker(asyncio.Lock())
            spoiler.args[0].callback.assert_awaited_once()
            archive.args[0].callback.assert_awaited_once()
            main._register_pyrogram_handlers = Mock(wraps=main._register_pyrogram_handlers)
            main.start_all_clients = AsyncMock()
            main.loop = asyncio.get_running_loop()
            dispatcher = types.SimpleNamespace(include_router=Mock(), start_polling=AsyncMock(),
                                               update=types.SimpleNamespace(outer_middleware=Mock()))
            main.Dispatcher = lambda **kwargs: dispatcher
            main.restore_startup_notifications = AsyncMock()
            main.starting_tg_parse_dialogs_handler = AsyncMock()
            ready = asyncio.get_running_loop().create_future()
            monitoring = asyncio.create_task(main._start_dialog_monitor(ready))
            await asyncio.sleep(0)
            main.starting_tg_parse_dialogs_handler.assert_not_awaited()
            ready.set_result(None)
            await monitoring
            main.starting_tg_parse_dialogs_handler.assert_awaited_once()
            main.starting_tg_parse_dialogs_handler.reset_mock()
            main.start_update_notifier = AsyncMock()
            main.run_media_archiver = AsyncMock()
            main.run_avatar_archiver = AsyncMock()
            main.run_history_backfill = AsyncMock()
            main.run_runtime_health = AsyncMock()
            report = Mock()
            report.condition = __import__("threading").Condition()
            report.menu_ids = {}
            report.state = "running"
            main.current_reporter = lambda: report
            main.bot.me = AsyncMock()
            main.run_personal_archive_migration = AsyncMock()
            main.account_operations.recover_interrupted = AsyncMock()
            main.run_account_operations = AsyncMock()
            main.run_topic_reminders = AsyncMock()
            main.notify_missing_secrets = AsyncMock()
            main.register_bot_commands = AsyncMock()
            original_sleep = asyncio.sleep
            async def poll_once(*args, **kwargs):
                await original_sleep(0)
            dispatcher.start_polling.side_effect = poll_once
            try:
                asyncio.sleep = AsyncMock()
                await main.start_polling_bot()
                await original_sleep(0)
            finally:
                asyncio.sleep = original_sleep
            main.start_all_clients.assert_awaited_once()
            main.run_avatar_archiver.assert_awaited_once_with(loader.bot)
            main.bot.me.assert_awaited_once()
            report.finish.assert_called_once()
            main.restore_startup_notifications.assert_awaited_once_with(loader.bot, report)
            registered_clients = main._register_pyrogram_handlers.call_args.args[0]
            assert main.start_all_clients.call_args.args[0] is registered_clients
            assert registered_clients == [client]
            dispatcher.start_polling.assert_awaited_once_with(loader.bot, close_bot_session=False)
            middlewares = dispatcher.update.outer_middleware.call_args_list
            assert middlewares[0].args == (main.track_update_task,)
            assert isinstance(middlewares[1].args[0], main.AdminAccessMiddleware)
            assert not any(isinstance(item, main.AlbumMiddleware)
                           for item in main.router.business_message.middleware)
            client.stop.assert_awaited_once()
            assert await loader.session_manager.get_snapshot() == []
            await loader.bot.session.close()

            # Failures before clients start and during polling must close every
            # resource too. No real DB, sessions or Telegram calls are involved.
            main.bot.session.close = AsyncMock()
            async def skip_delays(seconds):
                await original_sleep(0)

            for phase in ("database", "account_recovery", "polling", "cancellation"):
                main.bot.session.close.reset_mock()
                main.close_database.reset_mock()
                main.connect_database.side_effect = RuntimeError("offline DB failure") if phase == "database" else None
                main.account_operations.recover_interrupted.side_effect = RuntimeError("offline recovery failure") if phase == "account_recovery" else None
                dispatcher.start_polling.side_effect = (
                    asyncio.CancelledError() if phase == "cancellation" else
                    RuntimeError("offline polling failure") if phase == "polling" else None
                )
                client.stop.reset_mock()
                await loader.session_manager.add(client)
                try:
                    asyncio.sleep = skip_delays
                    try:
                        await main.start_polling_bot()
                    except (RuntimeError, asyncio.CancelledError):
                        pass
                    else:
                        raise AssertionError("Injected failure must propagate")
                finally:
                    asyncio.sleep = original_sleep
                main.bot.session.close.assert_awaited_once()
                main.close_database.assert_awaited_once()
                client.stop.assert_awaited_once()
                assert await loader.session_manager.get_snapshot() == []

        try:
            asyncio.run(check())
        finally:
            loader.loop.close()
    """)
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", probe],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
