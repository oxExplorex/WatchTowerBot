"""Restore navigation independently of bootstrap's early HTTP transport."""
import asyncio
from concurrent.futures import TimeoutError as FutureTimeout

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from core.logging import bot_logger
from core.thread_tools import run_blocking
from db.main import get_admin_ids
from keyboards.inline.startup import close_keyboard
from services.notification_topics import delivery, send_startup_menu
from data.texts.topics import LOGS_TITLE
from data.texts.startup import UPDATE_PHASE, UPDATE_DETAIL


async def send_update_notice(bot, owner_id, text):
    return await delivery(bot).send(bot.send_message, owner_id, "logs", LOGS_TITLE,
        text=text, parse_mode="HTML", reply_markup=close_keyboard())


async def prepare_update_menu(message, reporter=None):
    """Keep progress out of Menu and reuse this panel after exec."""
    from data.texts.common import START_MESSAGE_TEXT
    from keyboards.main.start_keyboard import static_admin_keyboard
    from utils.panel import edit_panel
    from data.texts.topics import MENU_TITLE

    service = delivery(message.bot)
    if await service.enabled():
        thread_id = await service.ensure_thread(message.chat.id, "menu", MENU_TITLE)
        if thread_id is None or message.message_thread_id != thread_id:
            return  # An update notification in Logs must stay in Logs.
    elif message.message_thread_id is not None:
        return
    panel = await edit_panel(message, START_MESSAGE_TEXT, static_admin_keyboard())
    identity = getattr(panel, "message_id", None) or message.message_id
    if reporter is not None:
        with reporter.condition:
            reporter.menu_ids[message.chat.id] = identity
            reporter._save()


def use_runtime_transport(bot, reporter):
    """Keep the worker on the configured aiogram session, including its proxy."""
    from scripts.startup_status import DeliveryError
    loop = asyncio.get_running_loop()

    async def send(method, payload):
        try:
            operation = bot.edit_message_text if method == "editMessageText" else bot.send_message
            result = await operation(**payload)
            return {"message_id": result.message_id} if method == "sendMessage" else True
        except TelegramRetryAfter as error:
            raise DeliveryError(429, retry_after=error.retry_after) from None
        except TelegramForbiddenError:
            raise DeliveryError(403) from None
        except TelegramBadRequest as error:
            raise DeliveryError(400, unchanged="message is not modified" in error.message.casefold()) from None
        except Exception as error:
            raise DeliveryError(reason=type(error).__name__) from None

    def transport(method, payload):
        future = asyncio.run_coroutine_threadsafe(send(method, payload), loop)
        try:
            return future.result(timeout=5)
        except FutureTimeout:
            future.cancel()
            raise DeliveryError(reason="TimeoutError") from None

    with reporter.condition:
        reporter.transport = transport


async def announce_update(bot, reporter, current_version, latest_version):
    """Deliver through the configured bot session before the early HTTP worker."""
    use_runtime_transport(bot, reporter)
    with reporter.condition:
        reporter.phase = UPDATE_PHASE
        reporter.detail = UPDATE_DETAIL.format(current=current_version, latest=latest_version)
        text = reporter.render()
    for owner_id in reporter.recipients:
        try:
            message = await delivery(bot).send(bot.send_message, owner_id, "logs", LOGS_TITLE,
                text=text, parse_mode="HTML")
            with reporter.condition:
                reporter.message_ids[owner_id] = message.message_id
                reporter.sent_text[owner_id] = text
                if message.message_thread_id:
                    reporter.thread_ids[owner_id] = message.message_thread_id
                else:
                    reporter.thread_ids.pop(owner_id, None)
                reporter._save()
        except Exception as error:
            bot_logger.warning("Update start delivery failed: admin_id=%s error=%s", owner_id, type(error).__name__)


async def restore_startup_notifications(bot, reporter=None):
    if reporter is not None:
        bot._watchtower_restart_menus = dict(reporter.menu_ids)
    admin_ids = {owner for owner in await get_admin_ids() if owner > 10}
    for owner_id in sorted(admin_ids):
        try:
            await send_startup_menu(bot, owner_id)
        except Exception as error:
            bot_logger.warning("Startup menu delivery failed: admin_id=%s error=%s",
                               owner_id, type(error).__name__)
    if reporter is None:
        return
    # Let the early sender finish before trying the configured aiogram session.
    # This runs in a background task, so polling need not wait for its timeout.
    await run_blocking(reporter.close)
    with reporter.condition:
        if reporter.running:
            return
        text = reporter.render()
        pending = [(owner, reporter.message_ids.get(owner)) for owner in reporter.recipients
                   if owner in admin_ids and owner not in reporter.dismissed and reporter.sent_text.get(owner) != text]
    for owner_id, message_id in pending:
        try:
            if message_id:
                try:
                    await bot.edit_message_text(chat_id=owner_id, message_id=message_id,
                        text=text, parse_mode="HTML", reply_markup=close_keyboard())
                    with reporter.condition:
                        reporter.sent_text[owner_id] = text
                    continue
                except TelegramBadRequest as error:
                    if "message is not modified" in error.message.casefold():
                        continue
            message = await delivery(bot).send(bot.send_message, owner_id, "logs", LOGS_TITLE,
                text=text, parse_mode="HTML", reply_markup=close_keyboard())
            with reporter.condition:
                reporter.message_ids[owner_id] = message.message_id
                reporter.sent_text[owner_id] = text
                reporter._save()
        except Exception as error:
            bot_logger.warning("Startup result delivery failed: admin_id=%s error=%s",
                               owner_id, type(error).__name__)
