"""Only private conversations with people belong in the message archive."""
from utils.message_payload import enum_value

IGNORED_CHAT_IDS = frozenset({777000})


def chat_kind(chat):
    if getattr(chat, "is_bot", False):
        return "bot"
    kind = enum_value(getattr(chat, "type", None))
    if kind is None and getattr(chat, "id", 0) > 0:
        return "private"
    return kind or "unknown"


def archive_allowed(chat_id, kind):
    return chat_id > 0 and chat_id not in IGNORED_CHAT_IDS and kind == "private"
