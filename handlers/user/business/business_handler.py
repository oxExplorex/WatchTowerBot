from aiogram import html
from aiogram.filters import StateFilter
from aiogram.types import Message

import data.text as constant_text
from core.logging import bot_logger
from db.main import create_dump_chat_user, get_account_tg_to_user_id, get_dump_chat_user
from loader import bot, router
from utils.others import get_user_log_text


@router.business_message(StateFilter("*"))
async def any_business_message_handler(message: Message):
    try:
        admin_id = (await bot.get_business_connection(message.business_connection_id)).user.id
    except Exception:
        bot_logger.exception("Failed to resolve business connection admin")
        return

    chat_id = message.chat.id
    username = message.chat.username
    chat_name = message.chat.full_name or message.chat.title

    if await get_dump_chat_user(admin_id, chat_id):
        return

    bot_logger.info(
        constant_text.PARSER_LOG_NEW_CHAT_TEXT.format(
            user_id=admin_id,
            chat_id=chat_id,
            username=username,
            chat_name=chat_name,
        )
    )
    await create_dump_chat_user(admin_id, chat_id)

    quote = html.quote(chat_name) if chat_name else chat_name

    settings = await get_account_tg_to_user_id(admin_id)
    if not settings or not settings.is_active:
        return

    if settings.alert_new_chat:
        log_chat_id = settings.admin_id if settings.alert_new_chat_id < 10 else settings.alert_new_chat_id
        await bot.send_message(log_chat_id, get_user_log_text(1, chat_id, username, quote))
