import traceback

from aiogram.exceptions import (
    AiogramError,
    CallbackAnswerException,
    ClientDecodeError,
    DetailedAiogramError,
    RestartingTelegram,
    SceneException,
    TelegramAPIError,
    TelegramBadRequest,
    TelegramConflictError,
    TelegramEntityTooLarge,
    TelegramForbiddenError,
    TelegramMigrateToChat,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramUnauthorizedError,
    UnsupportedKeywordArgument,
)
from aiogram.types import ErrorEvent

from core.logging import bot_logger
from loader import router

_HANDLED_ERRORS = (
    (
        (
            AiogramError,
            DetailedAiogramError,
            CallbackAnswerException,
            SceneException,
            UnsupportedKeywordArgument,
        ),
        "AiogramError",
    ),
    (TelegramAPIError, "TelegramAPIError"),
    (TelegramUnauthorizedError, "TelegramUnauthorizedError"),
    (TelegramNetworkError, "TelegramNetworkError"),
    (TelegramRetryAfter, "TelegramRetryAfter"),
    (TelegramMigrateToChat, "TelegramMigrateToChat"),
    (TelegramBadRequest, "TelegramBadRequest"),
    (TelegramNotFound, "TelegramNotFound"),
    (TelegramConflictError, "TelegramConflictError"),
    (TelegramForbiddenError, "TelegramForbiddenError"),
    (TelegramServerError, "TelegramServerError"),
    (RestartingTelegram, "RestartingTelegram"),
    (TelegramEntityTooLarge, "TelegramEntityTooLarge"),
    (ClientDecodeError, "ClientDecodeError"),
)


@router.error()
async def errors_handler(event: ErrorEvent):
    stack = [(frame.filename, frame.lineno, frame.name) for frame in traceback.extract_tb(event.exception.__traceback__)]
    for error_types, label in _HANDLED_ERRORS:
        if isinstance(event.exception, error_types):
            bot_logger.error("%s: exception=%s update_id=%s stack=%s", label, type(event.exception).__name__, event.update.update_id, stack)
            return True

    bot_logger.error("Unhandled error: exception=%s update_id=%s stack=%s", type(event.exception).__name__, event.update.update_id, stack)
