import traceback
import time

from google.genai import types
from pyrogram import Client
from pyrogram.types import Message

import data.text as constant_text
import loader
from core.logging import bot_logger
from core.async_tools import tracked_job
from core.session_runtime import session_number_from_client
from data.config import GEMINI_ACTION_DEBUG, GEMINI_KEY
from db.main import (
    get_account_by_number,
    is_admin,
    has_personal_secret,
    get_user_gemini_proxy_config,
    set_user_gemini_proxy_health,
)
from services.gemini import GEMINI_MODEL_NAME as _GEMINI_MODEL_NAME, generate_with_proxy, request_gemini
from utils.archive_policy import IGNORED_CHAT_IDS


def _ai_debug(event: str, **fields) -> None:
    if not GEMINI_ACTION_DEBUG:
        return
    payload = " ".join(f"{key}={value}" for key, value in fields.items() if key != "session")
    bot_logger.debug(f"[ai] {event} {payload}".strip())


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
    return await request_gemini(
        parts, proxy_url, api_key=GEMINI_KEY,
        system_instruction=loader.gemini_system_instruction,
    )


async def _generate_with_gemini(admin_id: int, parts: list[types.Part]) -> str:
    return await generate_with_proxy(
        admin_id, parts, api_key=GEMINI_KEY, request=_request_gemini,
        get_proxy_config=get_user_gemini_proxy_config,
        set_proxy_health=set_user_gemini_proxy_health,
    )


@tracked_job
async def gemini_app_handler(client: Client, message: Message):
    if getattr(getattr(message, "chat", None), "id", None) in IGNORED_CHAT_IDS:
        return
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

    if not await is_admin(message.from_user.id):
        return

    if not await has_personal_secret(message.from_user.id):
        from middlewares.personal_secret import prompt_setup

        await prompt_setup(loader.bot, message.from_user.id)
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
