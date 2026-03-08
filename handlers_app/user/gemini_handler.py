import traceback

from google import genai
from google.genai import types
from pyrogram import Client
from pyrogram.types import Message

import data.text as constant_text
from core.logging import bot_logger
from core.session_runtime import session_number_from_client
from data.config import GEMINI_KEY
from data.gemini_safety import SAFETY_SETTINGS
from db.main import (
    disable_user_gemini_proxy,
    get_account_by_number,
    get_admins,
    get_user_gemini_proxy_config,
    set_user_gemini_proxy_health,
)
from loader import bot, gemini_system_instruction
from utils.proxy_utils import normalize_http_proxy_input


_GEMINI_MODEL_NAME = "gemini-2.0-flash"


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


async def _notify_proxy_disabled(admin_id: int, reason: str) -> None:
    admin_ids = {int(admin_id)}
    try:
        for item in await get_admins():
            if item.user_id and int(item.user_id) > 10:
                admin_ids.add(int(item.user_id))
    except Exception:
        bot_logger.error(traceback.format_exc())

    text = constant_text.GEMINI_PROXY_AUTO_DISABLED_TEXT.format(reason=reason)
    for target in admin_ids:
        try:
            await bot.send_message(target, text)
        except Exception:
            bot_logger.error(traceback.format_exc())


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


async def _generate_with_gemini(admin_id: int, parts: list[types.Part]) -> str:
    if not GEMINI_KEY:
        return constant_text.GEMINI_UNAVAILABLE_TEXT

    proxy_config = await get_user_gemini_proxy_config(admin_id)
    proxy_raw = proxy_config.get("proxy")
    enabled = int(proxy_config.get("enabled", 0) or 0)

    if not enabled or not proxy_raw:
        return constant_text.GEMINI_PROXY_REQUIRED_TEXT

    proxy_url = normalize_http_proxy_input(str(proxy_raw))
    if not proxy_url:
        await disable_user_gemini_proxy(admin_id, reason="invalid_proxy_format")
        return constant_text.GEMINI_PROXY_INVALID_TEXT

    http_options = types.HttpOptions(
        client_args={"proxy": proxy_url},
        async_client_args={"proxy": proxy_url},
    )
    client = genai.Client(api_key=GEMINI_KEY, http_options=http_options)

    config = types.GenerateContentConfig(
        system_instruction=gemini_system_instruction or None,
        safety_settings=SAFETY_SETTINGS,
    )

    try:
        response = await client.aio.models.generate_content(
            model=_GEMINI_MODEL_NAME,
            contents=[types.Content(role="user", parts=parts)],
            config=config,
        )
        await set_user_gemini_proxy_health(admin_id, is_ok=True)
        return _response_text(response)
    except Exception as exc:
        error_text = str(exc)
        await set_user_gemini_proxy_health(admin_id, is_ok=False, error=error_text[:250])

        if _is_proxy_transport_error(exc):
            await disable_user_gemini_proxy(admin_id, reason=error_text[:250])
            await _notify_proxy_disabled(admin_id, reason=error_text[:120])
            return constant_text.GEMINI_PROXY_DOWN_TEXT

        bot_logger.error(traceback.format_exc())
        return constant_text.GEMINI_UNAVAILABLE_TEXT


async def gemini_app_handler(client: Client, message: Message):
    session_number = session_number_from_client(client)
    account = await get_account_by_number(session_number) if session_number else None
    if not account or not account.is_active:
        return

    if not message.from_user or int(account.user_id) != int(message.from_user.id):
        return

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

    try:
        owner_id = int(account.admin_id or account.user_id)
        answer_text = await _generate_with_gemini(owner_id, parts)
        await message.edit_text(text=answer_text)
    except Exception:
        bot_logger.exception("Gemini generation failed")
        await message.edit_text(text=constant_text.GEMINI_UNAVAILABLE_TEXT)


