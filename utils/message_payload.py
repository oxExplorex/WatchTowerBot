"""Normalize Bot API and Kurigram messages without storing plaintext on disk."""
from datetime import datetime, timezone
from enum import Enum


def timestamp(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return int((value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp())
    return int(value)


def enum_value(value):
    result = getattr(value, "value", value)
    # Kurigram entity enum values are raw TL classes; Bot API uses string labels.
    if isinstance(value, Enum) and isinstance(result, type):
        return value.name.lower()
    return result


def channel_namespace(chat) -> bool:
    return enum_value(getattr(chat, "type", None)) in {"channel", "supergroup"}


def entities(items) -> list[dict]:
    result = []
    for item in items or []:
        value = {"type": enum_value(item.type), "offset": item.offset, "length": item.length}
        for key in ("url", "language", "custom_emoji_id"):
            field = getattr(item, key, None)
            if field is not None:
                value[key] = str(field)
        user = getattr(item, "user", None)
        if user is not None:
            value["user_id"] = user.id
        result.append(value)
    return result


def message_payload(message) -> dict:
    media = []
    for kind in ("photo", "video", "video_note", "document", "audio", "voice", "animation", "sticker"):
        value = getattr(message, kind, None)
        if not value:
            continue
        if isinstance(value, (list, tuple)):
            value = value[-1]
        item = {"kind": kind}
        for key in ("file_id", "file_unique_id", "file_size", "width", "height", "duration", "mime_type", "file_name", "ttl_seconds"):
            field = getattr(value, key, None)
            if field is not None:
                item[key] = field
        media.append(item)
    chat = message.chat
    username = getattr(chat, "username", None)
    message_id = getattr(message, "message_id", None) or getattr(message, "id", None)
    link = f"https://t.me/{username}/{message_id}" if username and channel_namespace(chat) else None
    user = getattr(message, "from_user", None)
    return {
        "text": str(message.text) if getattr(message, "text", None) is not None else None,
        "caption": str(message.caption) if getattr(message, "caption", None) is not None else None,
        "entities": entities(getattr(message, "entities", None)),
        "caption_entities": entities(getattr(message, "caption_entities", None)),
        "media": media,
        "has_media_spoiler": bool(getattr(message, "has_media_spoiler", False)),
        "link": link,
        "sender": {"id": user.id, "username": getattr(user, "username", None),
                   "name": getattr(user, "full_name", None)} if user else None,
    }
