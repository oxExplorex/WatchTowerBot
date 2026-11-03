"""
Telegram-related helper utilities.
"""


def is_bot_or_channel(chat_obj) -> bool:
    """
    Check if Telegram chat object is a bot or channel.

    Args:
        chat_obj: Pyrogram chat object with 'type' attribute

    Returns:
        True if chat is a bot or channel, False otherwise
    """
    chat_type = str(getattr(chat_obj, "type", "")).lower()
    return "bot" in chat_type or "channel" in chat_type
