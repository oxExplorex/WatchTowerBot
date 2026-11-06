"""Recognize saved Telegram media without trusting file extensions or HTML content."""
import json
from pathlib import PurePosixPath
import zlib


def media_mime(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "audio/wav"
    if data.startswith(b"fLaC"):
        return "audio/flac"
    if data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xff and data[1] & 0xe0 == 0xe0
            and data[1] & 0x18 != 0x08 and data[1] & 0x06 != 0):
        return "audio/mpeg"
    if len(data) >= 2 and data[0] == 0xff and data[1] & 0xf6 == 0xf0:
        return "audio/aac"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if len(data) > 12 and data[4:8] == b"ftyp":
        return "audio/mp4" if data[8:12] in (b"M4A ", b"M4B ") else "video/mp4"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    return "application/octet-stream"


def preview_kind(kind, mime=None, name=None):
    """Choose a native player; the HTTP endpoint still checks the actual bytes."""
    extension = PurePosixPath((name or "").lower()).suffix
    image = mime in {"image/jpeg", "image/png", "image/webp", "image/gif"} or extension in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    if kind == "animation":
        return "photo" if image else "animation"
    if kind != "document":
        return kind
    if image:
        return "photo"
    if mime in {"video/mp4", "video/webm", "video/quicktime"} or extension in {".mp4", ".webm", ".m4v", ".mov"}:
        return "video"
    if mime in {"audio/ogg", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/flac", "audio/mp4", "audio/aac"} or extension in {
            ".ogg", ".oga", ".opus", ".mp3", ".wav", ".flac", ".m4a", ".aac"}:
        return "audio"
    return None


def sticker_data(data):
    mime = media_mime(data)
    if mime.startswith("image/"):
        return {"format": "image"}
    if mime.startswith("video/"):
        return {"format": "video"}
    if not data.startswith(b"\x1f\x8b") or len(data) > 1024 * 1024:
        raise ValueError("Unsupported sticker")
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = decoder.decompress(data, 4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024 or not decoder.eof or decoder.unused_data:
        raise ValueError("Oversized or damaged sticker")
    value = json.loads(raw)
    if (not isinstance(value, dict) or not isinstance(value.get("layers"), list)
            or not 0 < value.get("w", 0) <= 1024 or not 0 < value.get("h", 0) <= 1024
            or not 0 < value.get("fr", 0) <= 120 or not 0 < value.get("op", 0) - value.get("ip", 0) <= 1200):
        raise ValueError("Invalid sticker animation")
    return {"format": "tgs", "animation": value}
