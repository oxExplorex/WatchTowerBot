import asyncio
import logging
import os

from scripts.startup_status import current_reporter, start_bootstrap_notifications

if __name__ == "__main__":
    from scripts.install_dependencies import ensure_project_dependencies

    startup_report = start_bootstrap_notifications()
    try:
        startup_report.update("Зависимости", "Проверка и подготовка библиотек")
        ensure_project_dependencies(progress=startup_report.dependencies)
        startup_report.update("Загрузка приложения", "Подключение обработчиков и служб")
    except BaseException as error:
        startup_report.fail(error)
        startup_report.close()
        raise

# Force UTF-8 for Windows console/log output.
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# Python 3.14: pyrogram expects an existing current event loop at import time.
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import SimpleEventIsolation
from pyrogram import Client, filters
from pyrogram.handlers import DeletedMessagesHandler, EditedMessageHandler, MessageHandler, RawUpdateHandler

from aiotask.telegram_parse_dialogs import scheduler as dialogs_scheduler, starting_tg_parse_dialogs_handler
from aiotask.update_notifier import start_update_notifier, update_scheduler
from core.async_tools import cancel_logged_tasks, create_logged_task, track_update_task
from core.thread_tools import run_blocking
from core.message_updates import remember_update_identity
from core.auth_sessions import auth_clients
from core.logging import bot_logger, install_global_exception_hooks
from core.session_runtime import managed_session_handler, start_all_clients, stop_all_clients
import data.text as constant_text
from data.config import admin_id_list
from db.main import close_database, connect_database
from filters.all_filters_app import file_spoiler_filter
from handlers import router
from handlers_app.user.chat_presence_sync import chat_presence_sync_handler
from handlers_app.user.file_spoiler import file_spoiler_handler
from handlers_app.user.gemini_handler import gemini_app_handler
from handlers_app.user.message_history import deleted_messages_handler, edited_message_handler
from loader import bot, initialize_runtime_state, loop, session_manager
from middlewares.media_group import AlbumMiddleware
from middlewares.update_user import UpdateUserMiddleware
from middlewares.admin_access import AdminAccessMiddleware
from middlewares.auth_session_cleanup import AuthSessionCleanupMiddleware
from middlewares.personal_secret import PersonalSecretMiddleware, notify_missing_secrets
from utils.others import send_log_to_active_bot
from services.media_archive import run_media_archiver
from services.avatar_archive import run_avatar_archiver
from services.history_backfill import run_history_backfill
from services.runtime_health import PollingHealth, run_runtime_health
from services.bot_commands import register_bot_commands
from services.personal_archive import run_personal_archive_migration
from services.account_operations import repository as account_operations, run_account_operations
from aiotask.topic_reminder import run_topic_reminders


def _handle_clients_start_result(task: asyncio.Task) -> None:
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    except Exception:
        bot_logger.exception("Telegram startup task result check failed")
        return

    if exc is None:
        return

    bot_logger.error("Telegram startup task failed: %s", type(exc).__name__)


async def _report_clients_start(clients_start_task, clients):
    try:
        await asyncio.shield(clients_start_task)
    except asyncio.CancelledError:
        return
    except Exception:
        pass
    reporter = current_reporter()
    if reporter is not None:
        ready = sum(bool(getattr(client, "is_initialized", False) and getattr(client, "is_connected", False)) for client in clients)
        reporter.session_result(ready, len(clients))


async def _start_dialog_monitor(clients_start_task):
    # Polling must not wait for userbot authentication. The first scan, however,
    # must run after clients actually finish startup rather than after a fixed sleep.
    await asyncio.shield(clients_start_task)
    await starting_tg_parse_dialogs_handler()


def _register_pyrogram_handlers(clients: list[Client]) -> None:
    from core.client_handlers import register_client_handlers

    register_client_handlers(clients)


async def _notify_admins_startup_failure(text: str) -> None:
    admin_ids = sorted({int(x) for x in admin_id_list if int(x) > 10})
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            bot_logger.exception(f"Failed to send startup failure notification to admin_id={admin_id}")


async def _shutdown_runtime(clients_start_task: asyncio.Task | None) -> None:
    if clients_start_task is not None:
        clients_start_task.cancel()
        await asyncio.gather(clients_start_task, return_exceptions=True)
    for scheduler in (dialogs_scheduler, update_scheduler):
        if scheduler.running:
            try:
                scheduler.shutdown(wait=False)
            except Exception:
                bot_logger.exception("Failed to shut down scheduler")
    # AsyncIOScheduler queues shutdown on the loop. Let it cancel its job futures.
    await asyncio.sleep(0)
    await cancel_logged_tasks()
    try:
        await auth_clients.close_all()
    except Exception as exc:
        bot_logger.error("Temporary authorization cleanup failed: %s", type(exc).__name__)
    try:
        await stop_all_clients()
    except Exception:
        bot_logger.exception("Failed to stop all Telegram clients during shutdown")
    try:
        await bot.session.close()
    finally:
        await close_database()


async def start_polling_bot():
    bot_logger.info("Starting bot bootstrap")
    install_global_exception_hooks(loop)
    clients_start_task = None
    auth_clients.resume()
    reporter = current_reporter()
    polling_health = PollingHealth()
    bot.session.middleware(polling_health)
    try:
        if reporter is not None:
            reporter.update("База данных", "Подключение, миграции и подготовка хранилища")
        try:
            await connect_database()
        except RuntimeError as exc:
            if "DB_ENCRYPTION_KEY is required" in str(exc):
                if reporter is not None:
                    reporter.finish(success=False, detail="Не задан DB_ENCRYPTION_KEY. Укажите ключ шифрования и запустите бот вручную.")
                else:
                    await _notify_admins_startup_failure(constant_text.STARTUP_MISSING_ENCRYPTION_KEY_TEXT)
            raise
        if reporter is not None:
            reporter.configure(bot.token, admin_id_list)
            reporter.update("Telegram-сессии", "Подготовка сохранённых авторизаций")
        await account_operations.recover_interrupted()
        await initialize_runtime_state()

        router.message.middleware(AlbumMiddleware())
        # Business history stores each album item as its own Telegram message.

        router.message.middleware(UpdateUserMiddleware())
        router.business_message.middleware(UpdateUserMiddleware())

        dispatcher = Dispatcher(events_isolation=SimpleEventIsolation())
        dispatcher.update.outer_middleware(track_update_task)
        dispatcher.update.outer_middleware(AdminAccessMiddleware())
        dispatcher.update.outer_middleware(AuthSessionCleanupMiddleware())
        dispatcher.update.outer_middleware(PersonalSecretMiddleware())
        dispatcher.include_router(router)

        runtime_sessions = await session_manager.get_snapshot()
        _register_pyrogram_handlers(runtime_sessions)

        clients_start_task = loop.create_task(start_all_clients(runtime_sessions))
        clients_start_task.add_done_callback(_handle_clients_start_result)
        if reporter is not None:
            reporter.sessions = f"Личные Telegram-сессии подключаются: {len(runtime_sessions)}."
            create_logged_task(_report_clients_start(clients_start_task, runtime_sessions), name="startup_session_status")
            reporter.update("Фоновые службы", "Запуск мониторинга, архива и проверки обновлений")
        create_logged_task(run_media_archiver(bot), name="media_archiver")
        create_logged_task(run_avatar_archiver(bot), name="avatar_archiver")
        create_logged_task(run_history_backfill(bot, session_manager), name="history_backfill")
        create_logged_task(run_runtime_health(session_manager, polling_health), name="runtime_health")
        create_logged_task(run_personal_archive_migration(bot), name="personal_archive_migration")
        create_logged_task(run_account_operations(bot), name="account_operations")
        create_logged_task(run_topic_reminders(bot), name="topic_reminders")
        create_logged_task(notify_missing_secrets(bot), name="secret_setup_notifications")
        create_logged_task(register_bot_commands(bot), name="bot_commands")

        create_logged_task(_start_dialog_monitor(clients_start_task), name="tg_parse_dialogs_handler")
        create_logged_task(start_update_notifier(), name="update_notifier_starter")

        if reporter is not None:
            reporter.update("Подключение бота", "Проверка Telegram и запуск обработчиков")
            await bot.me()
            reporter.finish(detail="Команды и Business-обработчики готовы. Откройте /start.")
        else:
            await send_log_to_active_bot(bot)
        bot_logger.info("Bot was started")

        await dispatcher.start_polling(bot, close_bot_session=False)
    except BaseException as error:
        if reporter is not None and reporter.state != "failed":
            reporter.fail(error)
            await run_blocking(reporter.close)
        elif reporter is None and isinstance(error, Exception):
            await _notify_admins_startup_failure(constant_text.STARTUP_FATAL_ERROR_TEXT.format(
                error=type(error).__name__))
        raise
    finally:
        bot.session.middleware.unregister(polling_health)
        await _shutdown_runtime(clients_start_task)


if __name__ == "__main__":
    install_global_exception_hooks(loop)
    try:
        loop.run_until_complete(start_polling_bot())
    except KeyboardInterrupt:
        bot_logger.info("Bot stopped by KeyboardInterrupt")
    except Exception:
        bot_logger.critical("Fatal error stopped bot process", exc_info=True)
        raise
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        finally:
            reporter = current_reporter()
            if reporter is not None:
                reporter.close()
            loop.close()
            logging.shutdown()
