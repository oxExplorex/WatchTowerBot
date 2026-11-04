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
    bot_logger.error(
        "%s: exception=%s update_id=%s stack=%s",
        type(error).__name__ if handled else "Unhandled error",
        type(error).__name__, event.update.update_id, stack,
    )
    return True if handled else None
