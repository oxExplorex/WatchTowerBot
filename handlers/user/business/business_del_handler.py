from aiogram.types import BusinessMessagesDeleted, Update

from loader import bot, router
from services.business_messages import business_contexts, business_event_key
from services.message_service import delete_message


@router.deleted_business_messages()
async def deleted_business_handler(message: BusinessMessagesDeleted, event_update: Update | None = None, business_account_contexts=None):
    contexts = business_account_contexts if business_account_contexts is not None else await business_contexts(message.business_connection_id)
    for context in contexts:
        for message_id in message.message_ids:
            await delete_message(bot, context, message_id, source="business", chat=message.chat,
                                 event_key=business_event_key(message, event_update))
