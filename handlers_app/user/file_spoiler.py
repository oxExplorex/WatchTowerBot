import asyncio
import os
import tempfile
import traceback
from html import escape

from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from aiogram.types import FSInputFile
from pyrogram import Client
from pyrogram.types import Message

import data.text as constant_text
from core.logging import bot_logger
from core.session_runtime import session_number_from_client
from db.main import get_account_by_number
from loader import bot

SEND_TIMEOUT_SECONDS = 180
SEND_ATTEMPTS = 3


def _safe_text(value: str | None, fallback: str = "Unknown") -> str:
    if not value:
        return fallback
    return escape(str(value))


def _session_display_name(account) -> str:
    return _safe_text(getattr(account, "number", None), fallback="Session")


def _sender_display_name(message: Message) -> str:
    sender = getattr(message, "from_user", None)
    if sender:
        full_name = " ".join(
            x for x in [getattr(sender, "first_name", None), getattr(sender, "last_name", None)] if x
        ).strip()
        return _safe_text(full_name or getattr(sender, "username", None), fallback="User")

    chat = getattr(message, "chat", None)
    return _safe_text(getattr(chat, "title", None), fallback="Chat")


def _message_link(message: Message) -> str | None:
    chat = getattr(message, "chat", None)
    message_id = getattr(message, "id", None)
    if not chat or not message_id:
        return None

    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}/{message_id}"

    chat_id = getattr(chat, "id", 0)
    chat_id_str = str(chat_id)
    if chat_id_str.startswith("-100"):
        return f"https://t.me/c/{chat_id_str[4:]}/{message_id}"

    if int(chat_id or 0) > 0:
        return f"tg://user?id={chat_id}"

    return None


def _entity_link(label: str, entity_id: int | None, fallback: str) -> str:
    if entity_id:
        return f"<a href=\"tg://user?id={entity_id}\">{_safe_text(label, fallback=fallback)}</a> <code>{entity_id}</code>"
    return _safe_text(label, fallback=fallback)


def _media_suffix(message: Message) -> str:
    if getattr(message, "photo", None):
        return ".jpg"
    if getattr(message, "video", None) or getattr(message, "video_note", None):
        return ".mp4"
    return ".bin"


async def _send_document_with_retry(chat_id: int, file_path: str, suffix: str, caption: str) -> None:
    last_error: Exception | None = None

    for attempt in range(1, SEND_ATTEMPTS + 1):
        try:
            media = FSInputFile(file_path, filename=f"ttl_media{suffix}")
            await bot.send_document(
                chat_id=chat_id,
                document=media,
                caption=caption,
                disable_content_type_detection=False,
                request_timeout=SEND_TIMEOUT_SECONDS,
            )
            return
        except TelegramRetryAfter as exc:
            last_error = exc
            await asyncio.sleep(max(exc.retry_after, 1))
        except TelegramNetworkError as exc:
            last_error = exc
            if attempt < SEND_ATTEMPTS:
                await asyncio.sleep(attempt)
            else:
                raise

    if last_error:
        raise last_error


async def file_spoiler_handler(client: Client, message: Message):
    session_number = session_number_from_client(client)
    if not session_number:
        return

    account = await get_account_by_number(session_number)
    if not account or not account.is_active:
        return

    if not int(getattr(account, "alert_spoiler_media", 1) or 0):
        return

    temp_path = None
    status_message = None
    try:
        os.makedirs("data/temp", exist_ok=True)

        source_chat = getattr(message, "chat", None)
        source_chat_id = getattr(source_chat, "id", None)
        source_chat_title = _safe_text(getattr(source_chat, "title", None), fallback="Private chat")

        session_line = _entity_link(_session_display_name(account), getattr(account, "user_id", None), "Session")
        sender_line = _entity_link(
            _sender_display_name(message),
            getattr(getattr(message, "from_user", None), "id", None),
            "User",
        )

        message_url = _message_link(message)
        chat_line = (
            f"<a href=\"{message_url}\">{source_chat_title}</a>"
            if message_url
            else f"{source_chat_title} <code>{source_chat_id or '-'}</code>"
        )

        status_text = constant_text.SPOILER_STATUS_TEXT.format(
            session=session_line,
            sender=sender_line,
            chat=chat_line,
        )
        status_message = await bot.send_message(
            chat_id=account.admin_id,
            text=status_text,
            disable_web_page_preview=True,
        )

        suffix = _media_suffix(message)
        with tempfile.NamedTemporaryFile(prefix="spoiler_", suffix=suffix, dir="data/temp", delete=False) as tmp:
            temp_path = tmp.name

        downloaded = await client.download_media(message, file_name=temp_path)
        if not downloaded:
            if status_message:
                await status_message.edit_text(constant_text.SPOILER_DOWNLOAD_FAILED_TEXT)
            return

        caption = constant_text.SPOILER_SAVED_CAPTION_TEXT.format(
            session=session_line,
            sender=sender_line,
            chat=chat_line,
        )

        await _send_document_with_retry(account.admin_id, downloaded, suffix, caption)

        if status_message:
            try:
                await status_message.delete()
            except Exception:
                pass
    except Exception:
        bot_logger.error(traceback.format_exc())
        if status_message:
            try:
                await status_message.edit_text(constant_text.SPOILER_PROCESSING_ERROR_TEXT)
            except Exception:
                pass
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
