import traceback
from typing import Union

import aiogram
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import data.text as constant_text
from core.logging import bot_logger
from data.config import admin_id_list
from db.main import get_admins
from keyboards.main.start_keyboard import static_admin_keyboard
from loader import bot


async def send_log_to_active_bot(bot: aiogram.Bot):
    admin_ids = [
        user_id for user_id in set(admin_id_list + [x.user_id for x in await get_admins()]) if user_id > 10
    ]
    for admin_id in admin_ids:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=constant_text.NOTICE_ADMINISTRATOR_TO_ACTIVE_BOT,
                reply_markup=static_admin_keyboard(),
            )
        except Exception:
            pass


def get_user_log_text(action_id, chat_id, username, chat_name):
    link_id = f"tg://user?id={chat_id}"
    if action_id == 1:
        return constant_text.CHAT_LOG_NEW_TEXT.format(
            chat_name=chat_name,
            chat_id=chat_id,
            link_id=link_id,
            username=username,
        )
    if action_id == 2:
        return constant_text.CHAT_LOG_DELETED_TEXT.format(
            chat_name=chat_name,
            chat_id=chat_id,
            link_id=link_id,
            username=username,
        )
    return "error"


async def not_warning_delete_message(
    chat_id: int = None,
    message_id: int = None,
    message: Union[CallbackQuery, Message] = None,
) -> bool:
    if message is not None:
        if isinstance(message, Message):
            chat_id = message.chat.id
            message_id = message.message_id
        else:
            chat_id = message.message.chat.id
            message_id = message.message.message_id

    if chat_id is None or message_id is None:
        return False

    try:
        await bot.delete_message(chat_id, message_id)
        return True
    except Exception:
        bot_logger.error(traceback.format_exc())
        return False


async def close_state_pyrogram_client(state: FSMContext) -> None:
    """
    Safely close temporary Pyrogram client stored in FSM state.
    Prevents .session sqlite file lock on repeated auth attempts.
    """
    try:
        data = await state.get_data()
        app_temp = data.get("app_temp")
        if app_temp and getattr(app_temp, "is_connected", False):
            await app_temp.disconnect()
            bot_logger.info("Temporary auth client disconnected from FSM state")
    except Exception:
        bot_logger.error(traceback.format_exc())
