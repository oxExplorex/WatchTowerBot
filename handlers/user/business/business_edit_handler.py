from aiogram.types import Message, Update

from loader import bot, router
from services.business_messages import business_contexts, business_event_key
from services.message_service import save_message


@router.edited_business_message()
async def edited_business_handler(message: Message, event_update: Update | None = None, business_account_contexts=None):
    contexts = business_account_contexts if business_account_contexts is not None else await business_contexts(message.business_connection_id)
    for context in contexts:
        await save_message(bot, context, message, source="business", kind="edit",
                           event_key=business_event_key(message, event_update))
