from pyrogram import filters
from pyrogram.types import Message


def _is_ttl_enabled(obj) -> bool:
    ttl_value = getattr(obj, "ttl_seconds", None)
    return bool(ttl_value and int(ttl_value) > 0)


def file_with_spoiler_or_ttl(_, __, message: Message):
    photo = getattr(message, "photo", None)
    if photo:
        has_spoiler = bool(getattr(photo, "has_spoiler", False))
        return has_spoiler or _is_ttl_enabled(photo)

    video = getattr(message, "video", None)
    if video:
        has_spoiler = bool(getattr(video, "has_spoiler", False))
        return has_spoiler or _is_ttl_enabled(video)

    video_note = getattr(message, "video_note", None)
    if video_note:
        return _is_ttl_enabled(video_note)

    return False


file_spoiler_filter = filters.create(file_with_spoiler_or_ttl)
