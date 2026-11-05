import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import time

from aiogram.types import FSInputFile
from aiogram.exceptions import TelegramBadRequest

from core.account_runtime import account_guard
from core.logging import bot_logger
from data.texts.topics import ENABLE_TOPICS
from db.main import get_admin_ids, get_user_timezone_offset
from db.repositories.topics_repo import TopicsRepository
from db.session import get_session_factory
from services.notification_topics import delivery

TOPICS_IMAGE = Path(__file__).resolve().parents[1] / "assets/threaded-mode.png"


def next_midnight(now, offset):
    local = datetime.fromtimestamp(now, timezone(timedelta(hours=offset)))
    return int((local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


async def send_instruction_photo(bot, owner_id, repository):
    image_hash = hashlib.sha256(TOPICS_IMAGE.read_bytes()).hexdigest()
    async with account_guard(("reminder-photo", bot.id, image_hash)):
        file_id = await repository.get_photo(bot.id, image_hash)
        if file_id:
            try:
                return await bot.send_photo(chat_id=owner_id, photo=file_id,
                                            caption=ENABLE_TOPICS, parse_mode="HTML")
            except TelegramBadRequest as error:
                reason = error.message.casefold()
                if not any(marker in reason for marker in ("wrong file identifier", "file reference expired",
                        "file_reference_expired", "file_id_invalid", "invalid file id", "wrong remote file id")):
                    raise
                await repository.discard_photo(bot.id, image_hash, file_id)
        sent = await bot.send_photo(chat_id=owner_id, photo=FSInputFile(TOPICS_IMAGE),
                                    caption=ENABLE_TOPICS, parse_mode="HTML")
        if sent.photo:
            try:
                await repository.save_photo(bot.id, image_hash, sent.photo[-1].file_id)
            except Exception as error:
                # The reminder was delivered; a cache error must not repeat it.
                bot_logger.warning("Reminder photo cache update deferred: %s", type(error).__name__)
        return sent


async def remind_missing_topics(bot, *, now=None, repository=None):
    service = delivery(bot)
    if await service.enabled() is not False:
        return
    repository = repository or TopicsRepository(get_session_factory)
    now = int(time.time()) if now is None else now
    for owner_id in await get_admin_ids():
        try:
            deadline = next_midnight(now, await get_user_timezone_offset(owner_id))
            if not await repository.claim_reminder(bot.id, owner_id, now, deadline):
                continue
            if TOPICS_IMAGE.is_file():
                await send_instruction_photo(bot, owner_id, repository)
            else:
                await bot.send_message(chat_id=owner_id, text=ENABLE_TOPICS, parse_mode="HTML")
            await repository.postpone_reminder(bot.id, owner_id, deadline)
        except Exception as error:
            bot_logger.warning("Topic reminder deferred: %s", type(error).__name__)


async def run_topic_reminders(bot):
    while True:
        try:
            await remind_missing_topics(bot)
        except Exception as error:
            bot_logger.warning("Topic reminders unavailable: %s", type(error).__name__)
        await asyncio.sleep(30)
