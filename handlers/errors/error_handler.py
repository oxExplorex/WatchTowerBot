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


@router.error()
async def errors_handler(event: ErrorEvent):
    if isinstance(event.exception, (AiogramError, DetailedAiogramError, CallbackAnswerException, SceneException, UnsupportedKeywordArgument)):
        bot_logger.exception(f"AiogramError: {event.exception}\nUpdate: {event.update}")
        return True

    if isinstance(event.exception, TelegramAPIError):
        bot_logger.exception(f"TelegramAPIError: {event.exception}\nUpdate: {event.update}")
        return True

    if isinstance(event.exception, TelegramUnauthorizedError):
        bot_logger.exception(f"TelegramUnauthorizedError: {event.exception}\nUpdate: {event.update}")
        return True

    if isinstance(event.exception, TelegramNetworkError):
        bot_logger.exception(f"TelegramNetworkError: {event.exception}\nUpdate: {event.update}")
        return True

    if isinstance(event.exception, TelegramRetryAfter):
        bot_logger.exception(f"TelegramRetryAfter: {event.exception}\nUpdate: {event.update}")
        return True

    if isinstance(event.exception, TelegramMigrateToChat):
        bot_logger.exception(f"TelegramMigrateToChat: {event.exception}\nUpdate: {event.update}")
        return True

    if isinstance(event.exception, TelegramBadRequest):
        bot_logger.exception(f"TelegramBadRequest: {event.exception}\nUpdate: {event.update}")
        return True

    if isinstance(event.exception, TelegramNotFound):
        bot_logger.exception(f"TelegramNotFound: {event.exception}\nUpdate: {event.update}")
        return True

    if isinstance(event.exception, TelegramConflictError):
        bot_logger.exception(f"TelegramConflictError: {event.exception}\nUpdate: {event.update}")
        return True

    if isinstance(event.exception, TelegramForbiddenError):
        bot_logger.exception(f"TelegramForbiddenError: {event.exception}\nUpdate: {event.update}")
        return True

    if isinstance(event.exception, TelegramServerError):
        bot_logger.exception(f"TelegramServerError: {event.exception}\nUpdate: {event.update}")
        return True

    if isinstance(event.exception, RestartingTelegram):
        bot_logger.exception(f"RestartingTelegram: {event.exception}\nUpdate: {event.update}")
        return True

    if isinstance(event.exception, TelegramEntityTooLarge):
        bot_logger.exception(f"TelegramEntityTooLarge: {event.exception}\nUpdate: {event.update}")
        return True

    if isinstance(event.exception, ClientDecodeError):
        bot_logger.exception(f"ClientDecodeError: {event.exception}\nUpdate: {event.update}")
        return True

    bot_logger.exception(f"Update: {event.exception}\nUpdate: {event.update}")
    bot_logger.error(traceback.format_exc())
