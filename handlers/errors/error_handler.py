"""Report error types and locations without serializing Telegram updates."""
import traceback

from aiogram import Router
from aiogram.exceptions import AiogramError
from aiogram.types import ErrorEvent

from core.logging import bot_logger

router = Router(name=__name__)


@router.error()
async def errors_handler(event: ErrorEvent):
    error = event.exception
    stack = [(frame.filename, frame.lineno, frame.name) for frame in traceback.extract_tb(error.__traceback__)]
    handled = isinstance(error, AiogramError)
    reason = str(getattr(error, "message", "")).casefold()
    known = next((label for label, markers in {
        "callback_expired": ("query is too old", "query id is invalid", "query_id_invalid"),
        "message_unchanged": ("message is not modified",),
        "message_missing": ("message to edit not found", "message to delete not found"),
        "topic_missing": ("thread not found", "message_thread_invalid"),
    }.items() if any(marker in reason for marker in markers)), "unclassified")
    bot_logger.error(
        "%s: exception=%s update_id=%s method=%s reason=%s stack=%s",
        type(error).__name__ if handled else "Unhandled error",
        type(error).__name__, event.update.update_id, type(getattr(error, "method", None)).__name__, known, stack,
    )
    return True if handled else None
