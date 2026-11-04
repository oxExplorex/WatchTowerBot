"""Register the same userbot consumers at startup and after an ownership change."""


def register_client_handlers(clients):
    from pyrogram import Client, filters
    from pyrogram.handlers import DeletedMessagesHandler, EditedMessageHandler, MessageHandler, RawUpdateHandler

    from core.message_updates import remember_update_identity
    from core.session_runtime import managed_session_handler
    from filters.all_filters_app import file_spoiler_filter
    from handlers_app.user.chat_presence_sync import chat_presence_sync_handler
    from handlers_app.user.file_spoiler import file_spoiler_handler
    from handlers_app.user.gemini_handler import gemini_app_handler
    from handlers_app.user.message_history import deleted_messages_handler, edited_message_handler

    for client in clients:
        if not isinstance(client, Client):
            continue
        client.add_handler(RawUpdateHandler(remember_update_identity), group=-100)
        client.add_handler(MessageHandler(managed_session_handler(chat_presence_sync_handler), filters.all), group=0)
        client.add_handler(EditedMessageHandler(managed_session_handler(edited_message_handler)), group=0)
        client.add_handler(DeletedMessagesHandler(managed_session_handler(deleted_messages_handler)), group=0)
        client.add_handler(MessageHandler(managed_session_handler(gemini_app_handler), filters.text & filters.regex(r"^\.")), group=10)
        client.add_handler(MessageHandler(managed_session_handler(file_spoiler_handler),
            (filters.photo | filters.video | filters.video_note) & file_spoiler_filter), group=-10)
