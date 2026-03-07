from aiogram import html
from pyrogram import Client
from pyrogram.types import Message

from core.session_runtime import session_number_from_client
from db.main import create_dump_chat_user, get_account_by_number, get_dump_chat_user, update_user
from loader import bot
from utils.others import get_user_log_text


def _is_bot_or_channel(chat_obj) -> bool:
    chat_type = str(getattr(chat_obj, "type", "")).lower()
    return "bot" in chat_type or "channel" in chat_type


async def chat_presence_sync_handler(client: Client, message: Message):
    session_number = session_number_from_client(client)
    if not session_number:
        return

    account = await get_account_by_number(session_number)
    if not account or not account.is_active:
        return

    chat = getattr(message, "chat", None)
    if chat is None:
        return

    if not account.alert_bot and _is_bot_or_channel(chat):
        return

    chat_id = getattr(chat, "id", None)
    if chat_id is None:
        return

    exists = await get_dump_chat_user(account.user_id, chat_id)
    if exists:
        return

    username = getattr(chat, "username", None)
    chat_name = getattr(chat, "full_name", None) or getattr(chat, "title", None)

    if not chat_name:
        from_user = getattr(message, "from_user", None)
        first = getattr(from_user, "first_name", None)
        last = getattr(from_user, "last_name", None)
        chat_name = " ".join(x for x in [first, last] if x) or "Unknown"

    await update_user(chat_id, username, chat_name)
    await create_dump_chat_user(account.user_id, chat_id)

    if not account.alert_new_chat:
        return

    target_id = account.admin_id if account.alert_new_chat_id < 10 else account.alert_new_chat_id
    await bot.send_message(target_id, get_user_log_text(1, chat_id, username or "-", html.quote(chat_name)))
