"""Restore navigation independently of bootstrap's early HTTP transport."""
from aiogram.exceptions import TelegramBadRequest

from core.logging import bot_logger
from core.thread_tools import run_blocking
from db.main import get_admin_ids
from keyboards.inline.navigation import navigation_keyboard
from services.notification_topics import delivery, send_startup_menu
from data.texts.topics import LOGS_TITLE


async def restore_startup_notifications(bot, reporter=None):
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
                   if owner in admin_ids and reporter.sent_text.get(owner) != text]
    for owner_id, message_id in pending:
        try:
            if message_id:
                try:
                    await bot.edit_message_text(chat_id=owner_id, message_id=message_id,
                        text=text, parse_mode="HTML", reply_markup=navigation_keyboard())
                    continue
                except TelegramBadRequest as error:
                    if "message is not modified" in error.message.casefold():
                        continue
            await delivery(bot).send(bot.send_message, owner_id, "logs", LOGS_TITLE,
                text=text, parse_mode="HTML", reply_markup=navigation_keyboard())
        except Exception as error:
            bot_logger.warning("Startup result delivery failed: admin_id=%s error=%s",
                               owner_id, type(error).__name__)
