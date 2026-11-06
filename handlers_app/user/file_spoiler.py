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
from core.async_tools import tracked_job
from core.logging import bot_logger
from core.session_runtime import session_number_from_client
from db.main import get_account_by_number
from loader import bot
from utils.archive_policy import IGNORED_CHAT_IDS
from services.archive_policy import assess_chat

SEND_TIMEOUT_SECONDS = 180
SEND_ATTEMPTS = 3


def _safe_text(value: str | None, fallback: str = "Unknown") -> str:
    if not value:
        return fallback
    return escape(str(value))


def _sender_display_name(message: Message) -> str:
    sender = getattr(message, "from_user", None)
    if sender:
        full_name = " ".join(
            x for x in [getattr(sender, "first_name", None), getattr(sender, "last_name", None)] if x
        ).strip()
        return full_name or getattr(sender, "username", None) or "Пользователь"

    chat = getattr(message, "chat", None)
    return getattr(chat, "title", None) or "Чат"


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


def _entity_link(label: str | None, entity_id: int | None, fallback: str) -> str:
    if entity_id:
        if not label or str(label) == str(entity_id):
            return f'<a href="tg://user?id={entity_id}">{entity_id}</a>'
        return f"<a href=\"tg://user?id={entity_id}\">{_safe_text(label, fallback=fallback)}</a> · <code>{entity_id}</code>"
    return _safe_text(label, fallback=fallback)


def _media_kind(message: Message) -> str:
    for kind in ("photo", "video", "video_note"):
        if getattr(message, kind, None):
            return kind
    raise ValueError("Unsupported temporary media")


async def _send_media_with_retry(chat_id: int, file_path: str, kind: str, caption: str):
    last_error: Exception | None = None
    suffix = ".jpg" if kind == "photo" else ".mp4"

    for attempt in range(1, SEND_ATTEMPTS + 1):
        try:
            media = FSInputFile(file_path, filename=f"temporary_{kind}{suffix}")
            arguments = {kind: media, "request_timeout": SEND_TIMEOUT_SECONDS}
            if kind != "video_note":
                arguments.update(caption=caption, parse_mode="HTML")
            if kind == "video":
                arguments["supports_streaming"] = True
            from services.notification_topics import send_spoiler
            sent = await send_spoiler(
                bot, getattr(bot, f"send_{kind}"), chat_id, **arguments,
            )
            return sent
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


@tracked_job
async def file_spoiler_handler(client: Client, message: Message):
    if getattr(getattr(message, "chat", None), "id", None) in {bot.id, *IGNORED_CHAT_IDS}:
        return
    session_number = session_number_from_client(client)
    if not session_number:
        return

    account = await get_account_by_number(session_number)
    if not account or not account.is_active:
        return

    if not int(getattr(account, "alert_spoiler_media", 1) or 0):
        return
    if await assess_chat(account.user_id, message.chat,
                         sender=getattr(message, "from_user", None)) is None:
        return

    temp_path = None
    status_message = None
    try:
        os.makedirs("data/temp", exist_ok=True)

        source_chat = getattr(message, "chat", None)
        source_chat_id = getattr(source_chat, "id", None)
        private_name = " ".join(value for value in (
            getattr(source_chat, "first_name", None), getattr(source_chat, "last_name", None)) if value)
        source_chat_title = _safe_text(getattr(source_chat, "title", None) or private_name, fallback="Личная переписка")

        session_line = _entity_link(None, getattr(account, "user_id", None), "Аккаунт")
        sender_line = _entity_link(
            _sender_display_name(message),
            getattr(getattr(message, "from_user", None), "id", None),
            "Пользователь",
        )

        message_url = _message_link(message)
        chat_line = (
            f"<a href=\"{escape(message_url, quote=True)}\">{source_chat_title}</a>"
            if message_url
            else f"{source_chat_title} <code>{source_chat_id or '-'}</code>"
        )

        status_text = constant_text.SPOILER_STATUS_TEXT.format(
            session=session_line,
            sender=sender_line,
            chat=chat_line,
        )
        from services.notification_topics import send_spoiler
        status_message = await send_spoiler(
            bot, bot.send_message, account.admin_id,
            text=status_text,
            disable_web_page_preview=True,
            parse_mode="HTML",
        )

        kind = _media_kind(message)
        suffix = ".jpg" if kind == "photo" else ".mp4"
        with tempfile.NamedTemporaryFile(prefix="spoiler_", suffix=suffix, dir="data/temp", delete=False) as tmp:
            temp_path = tmp.name

        downloaded = await client.download_media(message, file_name=temp_path)
        if not downloaded:
            if status_message:
                await status_message.edit_text(constant_text.SPOILER_DOWNLOAD_FAILED_TEXT)
            return

        caption = constant_text.SPOILER_SAVED_CAPTION_TEXT.format(
            media=constant_text.SPOILER_MEDIA_TITLES[kind],
            session=session_line,
            sender=sender_line,
            chat=chat_line,
        )

        sent = await _send_media_with_retry(account.admin_id, downloaded, kind, caption)
        if kind == "video_note":
            from aiogram.types import ReplyParameters
            try:
                await bot.send_message(chat_id=account.admin_id, text=caption,
                    message_thread_id=sent.message_thread_id,
                    reply_parameters=ReplyParameters(message_id=sent.message_id),
                    disable_web_page_preview=True, parse_mode="HTML")
            except Exception:
                # Video notes have no captions; preserve context as a standalone message.
                await send_spoiler(bot, bot.send_message, account.admin_id, text=caption,
                                   disable_web_page_preview=True, parse_mode="HTML")

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
