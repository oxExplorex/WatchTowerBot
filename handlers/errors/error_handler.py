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
    for error_types, label in _HANDLED_ERRORS:
        if isinstance(event.exception, error_types):
            bot_logger.exception(f"{label}: {event.exception}\nUpdate: {event.update}")
            return True

    bot_logger.exception(f"Unhandled error: {event.exception}\nUpdate: {event.update}")
    bot_logger.error(traceback.format_exc())
