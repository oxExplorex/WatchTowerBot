import asyncio
import logging
import os

from scripts.migrate_telegram_sessions import migrate_legacy_sessions

if __name__ == "__main__":
    from scripts.install_dependencies import ensure_project_dependencies

    ensure_project_dependencies()

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
from services.personal_archive import run_personal_archive_migration


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


def _register_pyrogram_handlers(clients: list[Client]) -> None:
    for app in clients:
        if not isinstance(app, Client):
            continue

        app.add_handler(RawUpdateHandler(remember_update_identity), group=-100)
        # Each independent consumer gets its own group: a match otherwise prevents
        # the following handlers in that group from seeing this update.
        app.add_handler(MessageHandler(managed_session_handler(chat_presence_sync_handler), filters.all), group=0)
        app.add_handler(EditedMessageHandler(managed_session_handler(edited_message_handler)), group=0)
        app.add_handler(DeletedMessagesHandler(managed_session_handler(deleted_messages_handler)), group=0)
        app.add_handler(MessageHandler(managed_session_handler(gemini_app_handler), filters.text & filters.regex(r"^\.")), group=10)
        app.add_handler(
            MessageHandler(
                managed_session_handler(file_spoiler_handler),
                (filters.photo | filters.video | filters.video_note) & file_spoiler_filter,
            ), group=-10
        )


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
    try:
        try:
            await connect_database()
        except RuntimeError as exc:
            if "DB_ENCRYPTION_KEY is required" in str(exc):
                await _notify_admins_startup_failure(constant_text.STARTUP_MISSING_ENCRYPTION_KEY_TEXT)
            raise
        await asyncio.to_thread(migrate_legacy_sessions)
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
        create_logged_task(run_media_archiver(bot), name="media_archiver")
        create_logged_task(run_personal_archive_migration(bot), name="personal_archive_migration")
        create_logged_task(notify_missing_secrets(bot), name="secret_setup_notifications")

        # Technical delay for stable startup of pyrogram sessions.
        await asyncio.sleep(5)
        create_logged_task(starting_tg_parse_dialogs_handler(), name="tg_parse_dialogs_handler")
        create_logged_task(start_update_notifier(), name="update_notifier_starter")

        await send_log_to_active_bot(bot)
        bot_logger.info("Bot was started")

        await dispatcher.start_polling(bot, close_bot_session=False)
    finally:
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
            loop.close()
            logging.shutdown()
