from aiogram.exceptions import TelegramBadRequest


async def answer_callback(call):
    """A delayed click may outlive Telegram's acknowledgement window."""
    try:
        await call.answer()
    except TelegramBadRequest as error:
        reason = error.message.casefold()
        if not any(marker in reason for marker in ("query is too old", "query id is invalid", "query_id_invalid")):
            raise
