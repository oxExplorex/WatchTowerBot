from pyrogram import Client
from pyrogram.types import Message

from core.async_tools import tracked_job
from core.session_runtime import session_number_from_client
from db.main import get_account_by_number
from loader import bot
from core.message_updates import current_update_identity
from services.message_service import AccountContext, save_message


@tracked_job
async def chat_presence_sync_handler(client: Client, message: Message):
    session_number = session_number_from_client(client)
    if not session_number:
        return

    account = await get_account_by_number(session_number)
    if not account:
        return
    context = AccountContext.from_account(account)
    if context is not None:
        await save_message(bot, context, message, source="userbot", kind="new",
                           event_key=current_update_identity(client))
