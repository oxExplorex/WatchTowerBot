from core.async_tools import tracked_job
from core.message_updates import current_update_identity
from core.session_runtime import session_number_from_client
from db.main import get_account_by_number
from loader import bot
from services.message_service import AccountContext, delete_message, save_message


async def _context(client):
    number = session_number_from_client(client)
    account = await get_account_by_number(number) if number else None
    return AccountContext.from_account(account) if account else None


@tracked_job
async def edited_message_handler(client, message):
    context = await _context(client)
    if context is not None:
        await save_message(bot, context, message, source="userbot", kind="edit",
                           event_key=current_update_identity(client))


@tracked_job
async def deleted_messages_handler(client, messages):
    context = await _context(client)
    if context is None:
        return
    for message in messages:
        if message.id > 0:
            await delete_message(bot, context, message.id, source="userbot",
                                 chat=message.chat, event_key=current_update_identity(client))
