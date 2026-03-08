import asyncio
import os

# Force UTF-8 for Windows console/log output.
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# Python 3.14: pyrogram expects an existing current event loop at import time.
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from aiogram import Dispatcher
from pyrogram import Client, compose, filters
from pyrogram.handlers import MessageHandler

from aiotask.telegram_parse_dialogs import starting_tg_parse_dialogs_handler
from aiotask.update_notifier import start_update_notifier
from core.logging import bot_logger
from db.main import close_database, connect_database
from filters.all_filters_app import file_spoiler_filter
from handlers import router
from handlers_app.user.chat_presence_sync import chat_presence_sync_handler
from handlers_app.user.file_spoiler import file_spoiler_handler
from handlers_app.user.gemini_handler import gemini_app_handler
from loader import apps_session, bot, initialize_runtime_state, loop
from middlewares.media_group import AlbumMiddleware
from middlewares.update_user import UpdateUserMiddleware
from utils.others import send_log_to_active_bot


def _handle_compose_task_result(task: asyncio.Task) -> None:
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    except Exception:
        bot_logger.exception("compose() task result check failed")
        return

    if exc is None:
        return

    bot_logger.error(f"compose() failed: {exc.__class__.__name__}: {exc}")


def _register_pyrogram_handlers() -> None:
    for app in apps_session:
        if not isinstance(app, Client):
            continue

        app.add_handler(MessageHandler(gemini_app_handler, filters.text & filters.regex(r"^\.")))
        app.add_handler(MessageHandler(chat_presence_sync_handler, filters.all))
        app.add_handler(
            MessageHandler(
                file_spoiler_handler,
                (filters.photo | filters.video | filters.video_note) & file_spoiler_filter,
            )
        )


async def start_polling_bot():
    bot_logger.info("Starting bot bootstrap")
    await connect_database()
    try:
        await initialize_runtime_state()

        router.message.middleware(AlbumMiddleware())
        router.business_message.middleware(AlbumMiddleware())

        router.message.middleware(UpdateUserMiddleware())
        router.business_message.middleware(UpdateUserMiddleware())

        dispatcher = Dispatcher()
        dispatcher.include_router(router)

        _register_pyrogram_handlers()

        compose_task = loop.create_task(compose(apps_session))
        compose_task.add_done_callback(_handle_compose_task_result)

        # Technical delay for stable startup of pyrogram sessions.
        await asyncio.sleep(5)
        asyncio.create_task(starting_tg_parse_dialogs_handler())
        asyncio.create_task(start_update_notifier())

        await send_log_to_active_bot(bot)
        bot_logger.info("Bot was started")

        await dispatcher.start_polling(bot)
    finally:
        await close_database()


if __name__ == "__main__":
    loop.run_until_complete(start_polling_bot())
