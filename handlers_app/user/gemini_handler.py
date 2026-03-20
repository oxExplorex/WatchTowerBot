import traceback
import time

from google import genai
from google.genai import types
from pyrogram import Client
from pyrogram.types import Message

import data.text as constant_text
import loader
from core.logging import bot_logger
from core.session_runtime import session_number_from_client
from data.config import GEMINI_ACTION_DEBUG, GEMINI_KEY
from data.gemini_safety import SAFETY_SETTINGS
from db.main import (
    get_account_by_number,
    get_user_gemini_proxy_config,
    set_user_gemini_proxy_health,
)
from utils.proxy_utils import normalize_http_proxy_input


_GEMINI_MODEL_NAME = "gemini-3.1-flash-lite-preview"


def _ai_debug(event: str, **fields) -> None:
    if not GEMINI_ACTION_DEBUG:
        return
    payload = " ".join(f"{key}={value}" for key, value in fields.items())
    bot_logger.debug(f"[ai] {event} {payload}".strip())


def _response_text(response: object) -> str:
    text = getattr(response, "text", None)
    if text:
        return str(text).replace("\\n", "\n")

    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        parts = getattr(content, "parts", None) or []
        chunks: list[str] = []
        for part in parts:
            part_text = getattr(part, "text", None)
            if part_text:
                chunks.append(str(part_text))
        if chunks:
            return "\n".join(chunks)

    return constant_text.GEMINI_UNAVAILABLE_TEXT


def _is_proxy_transport_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = (
        "proxy",
        "tunnel",
        "connection",
        "connecterror",
        "network",
        "timeout",
        "name or service not known",
        "nodename nor servname provided",
    )
    return any(marker in text for marker in markers)


def get_answer_text_pre(reply_message: Message | None) -> str:
    if not reply_message:
        return constant_text.GEMINI_THINKING_TEXT

    if reply_message.animation or reply_message.video or reply_message.video_note or (
        reply_message.sticker and reply_message.sticker.is_video
    ):
        return constant_text.GEMINI_ANALYZING_VIDEO_TEXT
    if reply_message.voice or reply_message.audio:
        return constant_text.GEMINI_ANALYZING_AUDIO_TEXT
    if reply_message.sticker:
        return constant_text.GEMINI_ANALYZING_STICKER_TEXT
    if reply_message.photo:
        return constant_text.GEMINI_ANALYZING_PHOTO_TEXT
    return constant_text.GEMINI_ANALYZING_CONTENT_TEXT


def _get_mime_type(reply_message: Message | None) -> str | None:
    if not reply_message:
        return None

    if reply_message.animation or reply_message.video or reply_message.video_note or (
        reply_message.sticker and reply_message.sticker.is_video
    ):
        return "video/mp4"
    if reply_message.voice:
        return "audio/ogg"
    if reply_message.audio:
        return "audio/mpeg"
    if reply_message.photo or reply_message.sticker:
        return "image/png"
    return None


def _build_text(text: str, message: Message, has_media: bool) -> str:
    user_id = message.from_user.id if message.from_user else "-"
    username = message.from_user.username if message.from_user else None
    full_name = message.from_user.full_name if message.from_user else "-"
    username_text = f"@{username}" if username else "@-"

    prefix = f"[Message from {username_text} ({user_id}) | {full_name}]"
    if has_media:
        prefix = f"[Message with attachment from {username_text} ({user_id}) | {full_name}]"
    return f"{prefix} {text}".strip()


async def _request_gemini(parts: list[types.Part], proxy_url: str | None) -> str:
    if proxy_url:
        http_options = types.HttpOptions(
            client_args={"proxy": proxy_url},
            async_client_args={"proxy": proxy_url},
        )
        client = genai.Client(api_key=GEMINI_KEY, http_options=http_options)
    else:
        client = genai.Client(api_key=GEMINI_KEY)

    config = types.GenerateContentConfig(
        system_instruction=loader.gemini_system_instruction or None,
        safety_settings=SAFETY_SETTINGS,
    )

    response = await client.aio.models.generate_content(
        model=_GEMINI_MODEL_NAME,
        contents=[types.Content(role="user", parts=parts)],
        config=config,
    )
    return _response_text(response)


async def _generate_with_gemini(admin_id: int, parts: list[types.Part]) -> str:
    if not GEMINI_KEY:
        return constant_text.GEMINI_UNAVAILABLE_TEXT

    proxy_config = await get_user_gemini_proxy_config(admin_id)
    proxy_raw = proxy_config.get("proxy")
    enabled = int(proxy_config.get("enabled", 0) or 0)

    proxy_url: str | None = None
    if enabled and proxy_raw:
        proxy_url = normalize_http_proxy_input(str(proxy_raw))
        if not proxy_url:
            await set_user_gemini_proxy_health(admin_id, is_ok=False, error="invalid_proxy_format")
            return constant_text.GEMINI_PROXY_INVALID_TEXT

    try:
        answer = await _request_gemini(parts, proxy_url=proxy_url)
        await set_user_gemini_proxy_health(admin_id, is_ok=True)
        return answer
    except Exception as exc:
        error_text = str(exc)
        await set_user_gemini_proxy_health(admin_id, is_ok=False, error=error_text[:250])

        # Proxy mode failed at transport layer: keep saved proxy and retry once without proxy.
        if proxy_url and _is_proxy_transport_error(exc):
            try:
                return await _request_gemini(parts, proxy_url=None)
            except Exception:
                bot_logger.error(traceback.format_exc())
                return getattr(constant_text, "GEMINI_PROXY_OR_VPN_HINT_TEXT", constant_text.GEMINI_UNAVAILABLE_TEXT)

        bot_logger.error(traceback.format_exc())
        if not proxy_url:
            return getattr(constant_text, "GEMINI_PROXY_OR_VPN_HINT_TEXT", constant_text.GEMINI_UNAVAILABLE_TEXT)
        return constant_text.GEMINI_UNAVAILABLE_TEXT


async def gemini_app_handler(client: Client, message: Message):
    started_at = time.monotonic()
    session_number = session_number_from_client(client)
    account = await get_account_by_number(session_number) if session_number else None
    if not account or not account.is_active:
        _ai_debug(
            "skip_account",
            session=session_number or "-",
            message_id=message.id,
        )
        return

    if not message.from_user or int(account.user_id) != int(message.from_user.id):
        _ai_debug(
            "skip_user_mismatch",
            session=session_number or "-",
            account_user_id=getattr(account, "user_id", None),
            incoming_user_id=getattr(getattr(message, "from_user", None), "id", None),
            message_id=message.id,
        )
        return

    owner_id = int(account.admin_id or account.user_id)
    _ai_debug(
        "start",
        admin_id=owner_id,
        user_id=message.from_user.id,
        session=session_number or "-",
        message_id=message.id,
    )

    prompt_root = (message.text or message.caption or "").replace(".", "", 1).strip()
    reply_message = message.reply_to_message
    reply_text = (reply_message.text or reply_message.caption or "").strip() if reply_message else ""

    await message.edit_text(get_answer_text_pre(reply_message))

    parts: list[types.Part] = []
    if prompt_root:
        parts.append(types.Part.from_text(text=_build_text(prompt_root, message, has_media=False)))

    if reply_message and reply_text:
        parts.append(types.Part.from_text(text=_build_text(reply_text, reply_message, has_media=False)))

    mime_type = _get_mime_type(reply_message)
    if mime_type and reply_message:
        media = await reply_message.download(in_memory=True)
        media_bytes = media.getbuffer().tobytes()
        parts.append(types.Part.from_bytes(data=media_bytes, mime_type=mime_type))

    if not parts:
        parts = [types.Part.from_text(text=_build_text("?", message, has_media=False))]

    _ai_debug(
        "prepared",
        admin_id=owner_id,
        user_id=message.from_user.id,
        session=session_number or "-",
        message_id=message.id,
        parts=len(parts),
        has_media=1 if mime_type else 0,
    )

    try:
        answer_text = await _generate_with_gemini(owner_id, parts)
        await message.edit_text(text=answer_text)
        _ai_debug(
            "success",
            admin_id=owner_id,
            user_id=message.from_user.id,
            session=session_number or "-",
            message_id=message.id,
            took_ms=int((time.monotonic() - started_at) * 1000),
        )
    except Exception:
        bot_logger.exception("Gemini generation failed")
        await message.edit_text(text=constant_text.GEMINI_UNAVAILABLE_TEXT)
        _ai_debug(
            "failed",
            admin_id=owner_id,
            user_id=message.from_user.id,
            session=session_number or "-",
            message_id=message.id,
            took_ms=int((time.monotonic() - started_at) * 1000),
        )
