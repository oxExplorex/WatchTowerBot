import google.generativeai as genai
from pyrogram import Client
from pyrogram.types import Message

import data.text as constant_text
from core.session_runtime import session_number_from_client
from db.main import get_account_by_number
from loader import chat_gemini


def get_answer_text(answer):
    return answer.text.replace("\\n", "\n")


def get_answer_text_pre(reply_message):
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


def _get_mime_type(reply_message):
    if not reply_message:
        return None
    if reply_message.animation or reply_message.video or reply_message.video_note or (
        reply_message.sticker and reply_message.sticker.is_video
    ):
        return "video/mp4"
    if reply_message.voice or reply_message.audio:
        return "audio/wav"
    if reply_message.photo or reply_message.sticker:
        return "image/png"
    return None


def _build_text(text, message: Message, has_media: bool):
    prefix = f"[Message from @{message.from_user.username} ({message.from_user.id}) | {message.from_user.full_name}]"
    if has_media:
        prefix = f"[Message with attachment from @{message.from_user.username} ({message.from_user.id}) | {message.from_user.full_name}]"
    return f"{prefix} {text}".strip()


async def gemini_app_handler(client: Client, message: Message):
    session_number = session_number_from_client(client)
    account = await get_account_by_number(session_number) if session_number else None
    if not account or not account.is_active:
        return

    if not message.from_user or int(account.user_id) != int(message.from_user.id):
        return

    if chat_gemini is None:
        return await message.reply_text(constant_text.GEMINI_UNAVAILABLE_TEXT)

    prompt_root = (message.text or message.caption or "").replace(".", "", 1)
    reply_text = (message.reply_to_message.text or message.reply_to_message.caption or "") if message.reply_to_message else ""

    await message.edit_text(get_answer_text_pre(message.reply_to_message))

    mime_type = _get_mime_type(message.reply_to_message)
    if mime_type and message.reply_to_message:
        media = await message.reply_to_message.download(in_memory=True)
        parts = [
            genai.protos.Part(text=_build_text(prompt_root, message, False)) if prompt_root else None,
            genai.protos.Part(text=_build_text(reply_text, message.reply_to_message, True)) if reply_text else None,
            genai.protos.Part(
                inline_data=genai.protos.Blob(
                    mime_type=mime_type,
                    data=media.getbuffer().tobytes(),
                )
            ),
        ]
        parts = [part for part in parts if part]
    else:
        parts = [
            genai.protos.Part(text=_build_text(prompt_root or "?", message, False)),
            genai.protos.Part(text=_build_text(reply_text or "?", message.reply_to_message or message, False)),
        ]

    response = await chat_gemini.send_message_async(
        content=genai.protos.Content(parts=parts),
    )

    await message.edit_text(text=get_answer_text(response))
