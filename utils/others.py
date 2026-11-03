import traceback
from typing import Union

import aiogram
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import data.text as constant_text
from core.logging import bot_logger
from core.auth_sessions import auth_clients
from data.config import admin_id_list
from db.main import get_admins
from keyboards.main.start_keyboard import static_admin_keyboard
from loader import bot
from utils.chat_notifications import get_user_log_text


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
            bot_logger.exception(f"Failed to send startup notification to admin_id={admin_id}")


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
        if app_temp:
            await auth_clients.discard(app_temp)
            bot_logger.info("Temporary auth client disconnected from FSM state")
    except Exception:
        bot_logger.error(traceback.format_exc())
